# PRD：YOLO11 检测框架运行问题修复

> 版本：v1.0　|　日期：2026-06-10　|　负责人：研发
> 范围：修复实测中发现的 5 个问题（GPU 未启用、进度条不同步、刷新后残留结果、数据库结果无法打开、结果视频无法播放）

---

## 0. 背景

本框架为 `web(Next.js) → nginx → api(FastAPI) → Redis Streams → worker(YOLO 推理) → Postgres` 的容器化流水线。实测中发现 4 个问题，本文档逐一给出**根因（基于代码定位）**与**解决方案**。

| 编号 | 现象 | 严重度 | 性质 |
|---|---|---|---|
| P1 | 推理不调用本机 RTX 3070 Ti，跑在 CPU 上 | 高 | 配置/架构缺陷 |
| P2 | 进度条长时间卡在 35%，然后直接跳 100% | 中 | 功能缺陷 |
| P3 | 网页刷新后中间/右侧仍残留上一次检测结果 | 中 | 前端逻辑缺陷 |
| P4 | `localhost:5432` 打不开，无法查看数据库结果 | 低 | 使用误解（非 Bug） |
| P5 | 检测完成后右侧结果视频黑屏、停在 0:00 无法播放 | 高 | 编码缺陷 |

---

## P1. 推理未使用 GPU（跑在 CPU 上）

### 现象
任务管理器显示 NVIDIA RTX 3070 Ti（GPU 1）利用率 0%，推理实际由 CPU/Intel 核显承担，速度很慢。

### 根因（三处叠加，缺一不可）
1. **Worker 镜像没有 CUDA 运行时**
   `worker/Dockerfile:1` 使用 `FROM python:3.11-slim`，镜像内无 CUDA/cuDNN。
2. **安装的是 CPU 版 PyTorch**
   `worker/requirements.txt` 仅声明 `ultralytics>=8.3.0`，pip 默认拉取 **CPU-only torch**，容器内 `torch.cuda.is_available()` 恒为 `False`。
3. **compose 没有把 GPU 暴露给容器**
   `docker-compose.yml` 的 `worker` 服务只有 `cpus`/`mem_limit`，**没有 GPU 预留**（`deploy.resources.reservations.devices` 或 `gpus`）。
4. **推理代码未指定 device**
   `worker/app/inference.py` 中 `model.predict(...)` 未传 `device=`，即使有 GPU 也不会强制使用。

> 结论：即便宿主机有独显，当前容器**从根本上看不到 GPU**，必然回落 CPU。

### 解决方案

**A. 配置项（新增 `YOLO_DEVICE`）**
- `worker/app/config.py` 的 `Settings` 增加：`yolo_device: str = "auto"`（auto / cpu / 0）。
- `.env`/`.env.example` 增加 `YOLO_DEVICE=auto`。

**B. 推理代码显式选择设备**　`worker/app/inference.py`
```python
import torch

def _resolve_device(settings) -> str:
    if settings.yolo_device != "auto":
        return settings.yolo_device
    return "0" if torch.cuda.is_available() else "cpu"
```
在 `model.predict(...)` 全部调用处加入 `device=_resolve_device(settings)`，并在 worker 启动日志打印 `torch.cuda.is_available()` 与设备名，便于核验。

**C. 让容器拿到 GPU（二选一）**

> 前提：Windows 宿主需 **Docker Desktop + WSL2 后端 + 最新 NVIDIA 驱动**，并启用 NVIDIA Container Toolkit。RTX 3070 Ti **Laptop** 在 Optimus/MUX 笔记本上能否直通，取决于驱动与 WSL2 GPU 支持。

- **方案 C1（推荐，容器内 GPU）**
  - `worker/Dockerfile` 改用 CUDA 基础镜像（如 `nvidia/cuda:12.x-cudnn-runtime-ubuntu22.04` + 安装 Python），或安装 CUDA 版 torch：
    `pip install torch --index-url https://download.pytorch.org/whl/cu121`
  - `docker-compose.yml` 的 `worker` 增加：
    ```yaml
    worker:
      gpus: all          # 或使用 deploy.resources.reservations.devices
      environment:
        YOLO_DEVICE: ${YOLO_DEVICE:-auto}
    ```
- **方案 C2（兜底，宿主机原生跑 worker）**
  若笔记本无法 WSL2 直通 GPU，则在宿主机的 `.venv` 内用 CUDA torch 直接运行 `python -m app.main`，仅用容器跑 redis/postgres/api/web。最省事、最稳。

**验收**：worker 启动日志显示 `cuda available: True / device: NVIDIA GeForce RTX 3070 Ti`；推理期间任务管理器 GPU 利用率明显上升；单张图/单帧推理耗时较 CPU 下降数倍。

---

## P2. 进度条卡在 35% 后直接跳 100%

### 现象
进度条长时间停在 35%，推理结束瞬间跳到 100%，与真实进度不同步。

### 根因
进度是**离散硬编码**的，推理过程中**不上报中间进度**。
`worker/app/main.py` `handle_job()` 只写三次进度：
- `update_job_status(job_id, "running", 10)`（接收）
- `update_job_status(job_id, "running", 35)`（开始推理）→ 然后调用 `detect_media(...)`
- `complete_job(...)`（完成，进度 100）

整段 `detect_media` 期间进度恒为 35。又因 `worker/app/inference.py` 的 `_yolo_video` **对每一帧都跑一次 `model.predict`** 并写帧，在 CPU 上极慢（叠加 P1），于是「卡 35% 很久」。前端 `web/app/page.tsx` 每 2.5s 轮询，只能拿到数据库里的 35，自然不动。

### 解决方案
让推理过程**按帧/进度回调**真实上报：
1. `_yolo_video` 用 `capture.get(cv2.CAP_PROP_FRAME_COUNT)` 取总帧数，循环中按 `frames/total` 把进度映射到 **35→95** 区间。
2. `detect_media`/`_yolo_video` 增加 `progress_cb` 回调参数；`handle_job` 传入一个把进度写库并 `publish status` 的协程封装（注意 worker 主循环是 async，OpenCV 帧循环是同步，可每 N 帧 `await` 一次上报，或用 `run_in_executor` + 线程安全队列上报）。
3. 上报节流：每处理 `max(1, total//50)` 帧上报一次，避免高频写库。
4. 图片任务：上报一个中间值（如 35→70→100）即可。

```python
# _yolo_video 内
total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
...
if total and frames % step == 0 and progress_cb:
    pct = 35 + int(60 * frames / total)   # 35→95
    progress_cb(min(95, pct))
```

**验收**：上传视频后进度条平滑增长（35→95→100），与日志中帧处理同步；前端轮询能看到中间值。

---

## P3. 刷新后中间/右侧残留上一次结果

### 现象
浏览器刷新后，中间「任务队列」自动选中最近一条已完成任务，右侧「结果与日志」直接显示上次的结果视频和检测 JSON，而不是干净的初始态。

### 根因
前端**初始化即自动选中最新任务**。
`web/app/page.tsx` 的 `refreshJobs()`：
```js
} else if (next[0]) {
  setSelected(next[0]);   // 没有已选时，默认选中列表第 0 条（最新一条）
}
```
首屏 `useEffect` 调 `refreshJobs()`，无 `selected` → 命中该分支 → 自动选中最近任务。随后两个 `useEffect` 监听 `selected`，加载 `result_url`（结果视频）与渲染 `result_json`，于是刷新即「残留上次结果」。这是设计逻辑，而非数据脏。

### 解决方案（任选其一，建议 1+3）
1. **首屏不自动选中**：去掉 `else if (next[0]) setSelected(next[0])`，仅在用户**点击任务**时才 `setSelected`。
2. **区分主动/被动刷新**：`refreshJobs(nextSelectedId?, {autoSelect=false})`，仅 `submit()` 创建任务后传 `autoSelect:true`。
3. **新增「清空/新建」按钮**：清空 `selected / selectedResultUrl / logs / uploaded / file / previewUrl`，回到初始态。
4. 结果区与 JSON 区在 `selected` 为空时严格显示占位文案（当前已有占位逻辑，去掉自动选中即生效）。

**验收**：刷新后右侧显示「选择已完成任务后显示结果图或视频」，中间无高亮选中；点击某条任务才展示其结果。

---

## P4. `localhost:5432` 打不开 / 无法查看数据库结果

### 现象
浏览器访问 `localhost:5432` 返回 `ERR_CONNECTION_RESET`（This site can't be reached）。

### 根因（这不是 Bug，是使用方式问题）
`5432` 是 **PostgreSQL 数据库通信端口**，走的是 Postgres 二进制协议，**不是 HTTP**。浏览器用 HTTP 去握手，Postgres 直接重置连接，所以报 `ERR_CONNECTION_RESET`。这是**预期行为**，数据库本身没问题（Docker 里 `postgres-1` 健康运行）。

检测结果其实已经存进了 Postgres：表 `detection_jobs.result_json`（JSONB），见 `api/app/models.py`。**前端右侧面板展示的 JSON 就是它**，无需直连数据库即可查看。

### 解决方案 / 正确做法
**查看数据库结果有三种正规方式：**

1. **用数据库客户端**（最直接）
   - 命令行：`docker exec -it postgres-1 psql -U yolo -d yolo -c "SELECT id,status,result_json FROM detection_jobs ORDER BY created_at DESC LIMIT 5;"`
   - GUI：DBeaver / TablePlus / Navicat，连接 `host=localhost port=5432 db=yolo user=yolo password=change_me_in_prod`。
2. **走 API**（已有接口）
   - `GET /api/jobs`、`GET /api/jobs/{id}`，结果含 `result_json`（需带 `X-API-Key: devkey1`）。
3. **Web 版数据库管理界面（已实现）—— Adminer 经 nginx 反代 + Basic Auth**
   为了让产品更完整，新增 Adminer 控制台，但**不直接暴露端口**，而是挂在 nginx 后面并加一层 HTTP Basic Auth 鉴权，统一入口、统一加固。

   - **服务定义**（`docker-compose.yml`）：
     ```yaml
     adminer:
       image: adminer:4
       environment:
         ADMINER_DEFAULT_SERVER: postgres
         ADMINER_DESIGN: dracula
       depends_on:
         postgres:
           condition: service_healthy
     ```
     注意：**不在 `docker-compose.override.yml` 暴露 8080 端口**，容器仅在内网可达，外部只能走 nginx。

   - **nginx 反代 + 鉴权**（`infra/nginx.conf`）：
     ```nginx
     location = /db { return 301 /db/; }
     location /db/ {
         auth_basic "YOLO DB Console";
         auth_basic_user_file /etc/nginx/.htpasswd;
         limit_req zone=api_rl burst=20 nodelay;
         limit_conn api_conn 10;
         proxy_pass http://adminer:8080/;
         proxy_http_version 1.1;
         proxy_set_header Host $host;
         proxy_set_header X-Real-IP $remote_addr;
         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
         proxy_set_header X-Forwarded-Proto $scheme;
     }
     ```
     说明：Adminer 资源用相对路径（`?file=default.css`），浏览器会解析到 `/db/` 前缀下，故子路径反代不破样式。

   - **口令文件**（`infra/.htpasswd`，挂载到 nginx `/etc/nginx/.htpasswd:ro`）：
     ```bash
     # 生成/修改账号口令（示例账号 admin）
     printf 'admin:%s\n' "$(openssl passwd -apr1 '你的强口令')" > infra/.htpasswd
     docker compose restart nginx
     ```

   - **访问方式**：浏览器开 `http://localhost/db/`，弹出 Basic Auth 输入框 → 账号 `admin` / 口令（默认占位 `change_me_in_prod`，**务必改掉**）→ 进入后系统选 PostgreSQL（服务器已默认 `postgres`），账号/库 `yolo`，即可浏览 `detection_jobs.result_json` 等表。

   - **安全要点**：
     - Adminer 端口不对外暴露，唯一入口是经鉴权的 `/db/`；
     - 默认口令 `change_me_in_prod` 仅为占位，上线前必须替换为强口令；
     - 生产环境务必启用 HTTPS（Basic Auth 明文传输，需 TLS 保护）；
     - `infra/.htpasswd` 应纳入密钥管理，不要提交真实生产口令到仓库。

> 注：`localhost:5432` 是数据库协议端口，**不应也无法用浏览器打开**；要可视化浏览请走上面的 `http://localhost/db/`。

**验收**：
- [ ] 直连 `localhost:8080` 连接被拒（端口未暴露）。
- [ ] `http://localhost/db/` 无凭据返回 401；带正确账号口令返回 200 并可浏览数据。
- [ ] 用 psql 或 Adminer 能看到 `detection_jobs.result_json` 中的检测框数据。

---

## P5. 检测完成后结果视频无法播放（黑屏 / 停在 0:00）

### 现象
任务「已完成」，右侧 RESULT VIEW 的视频窗口加载出来了（有播放控件），但画面全黑、时间停在 0:00，点击播放无反应；而左侧上传的**原视频**预览却能正常播放。检测 JSON 也正常显示。

### 根因
**worker 输出视频用了浏览器不支持的编码格式。**
`worker/app/inference.py:132`（及 demo 的 `:60`）写视频时用：
```python
cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
```
`mp4v` 是 **MPEG-4 Part 2** 编码。虽然容器后缀是 `.mp4`，但 Chrome / Edge 的 `<video>` 标签**不支持解码 mp4v**（浏览器只支持 H.264/avc1、VP8/9、AV1）。所以：
- 文件本身存在、API 也能下载（`FileResponse` 按 `.mp4` 返回 `video/mp4`）；
- 但浏览器拿到后**无法解码** → 黑屏、0:00、无法播放。
- 左侧原视频能播，是因为它是用户上传的源文件（通常已是 H.264），并非 worker 产物。

> 一句话：不是文件没生成，也不是传输坏了，而是**编码格式浏览器播不了**。

### 解决方案
把结果视频统一转成 **H.264（avc1）+ `+faststart`**（moov 前置，便于 Web 流式播放）。

**方案 A（推荐，最稳）：用 ffmpeg 转码**
1. `worker/Dockerfile` 安装 ffmpeg：
   `apt-get install -y --no-install-recommends ffmpeg`
2. `_yolo_video` 先用 OpenCV 写临时文件（`mp4v`），推理结束后调用 ffmpeg 转码为最终 `.mp4`：
   ```python
   import subprocess
   subprocess.run([
       "ffmpeg", "-y", "-i", str(tmp_path),
       "-c:v", "libx264", "-pix_fmt", "yuv420p",
       "-movflags", "+faststart", str(output_path),
   ], check=True)
   ```
   注意 `-pix_fmt yuv420p`：保证 Safari/部分浏览器兼容。

**方案 B（轻量，但有风险）：直接换 fourcc**
把 `*"mp4v"` 换成 `*"avc1"`。但 `opencv-python-headless` 因 H.264 授权问题，多数发行版**不带 H.264 编码器**，`avc1` 可能静默失败或写不出文件。**不建议作为唯一方案**，仅在确认本机 OpenCV 带 H.264 时可用。

**方案 C（边推理边转码）**：将 ffmpeg 作为子进程，用管道接收 OpenCV 帧（`rawvideo` → libx264），省去临时文件。实现稍复杂，体量大时可作优化项。

> 兼容性补充：H.264 的宽高建议为偶数（libx264 + yuv420p 要求），若源视频奇数分辨率需在写帧前 pad/裁剪到偶数，否则 ffmpeg 报错。

**验收**：检测完成后右侧视频可正常播放，进度条/时长正常；Chrome、Edge、Safari 均可播；JSON 与视频对应。

---

## 实施优先级与排期建议

| 优先级 | 项 | 说明 | 预估 |
|---|---|---|---|
| P0 | P5 结果视频转码 H.264 | 直接影响「看不看得到结果」，必须修 | 0.5–1d |
| P0 | P2 进度上报 | 纯软件改动，无环境依赖，体验提升明显 | 0.5d |
| P0 | P3 去掉自动选中 + 清空按钮 | 前端小改动 | 0.5d |
| P1 | P1 GPU 启用 | 依赖 WSL2/驱动，需先验证笔记本可直通；不行则走 C2 兜底 | 1–2d |
| P2 | P4 Adminer + 文档 | 可选增强，主要是说明 + 一个服务 | 0.5d |

## 总体验收清单
- [ ] worker 日志确认使用 CUDA；GPU 利用率上升；推理提速。
- [ ] 视频任务进度条 35→95→100 平滑同步。
- [ ] 刷新后为干净初始态，点击任务才显示结果；有「清空/新建」入口。
- [ ] 文档说明数据库查看方式；（可选）Adminer 可视化可用。
- [ ] 结果视频在 Chrome/Edge/Safari 均可正常播放。

## 影响文件清单
- `worker/Dockerfile`、`worker/requirements.txt`、`docker-compose.yml`（P1、P5 装 ffmpeg）
- `worker/app/config.py`、`worker/app/inference.py`、`worker/app/main.py`（P1、P2、P5）
- `.env` / `.env.example`（P1）
- `web/app/page.tsx`（P3）
- `docker-compose.yml`（新增 adminer 服务、nginx 挂载 .htpasswd + 依赖）、`infra/nginx.conf`（`/db/` 反代 + Basic Auth）、`infra/.htpasswd`（鉴权口令）+ 文档（P4，已实现）
