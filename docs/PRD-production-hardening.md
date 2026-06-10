# PRD：生产加固 / 认证 / 限流 / 配额

> 目标读者：实现工程师（Codex）。本文档要求**可直接落地**，所有路径、函数名、依赖均已与当前代码库核对。
> 适用版本：`api`（FastAPI 0.115）、`worker`、`web`（Next.js）、`docker-compose.yml`、`infra/nginx.conf`。

---

## 0. 背景与现状（必读）

当前架构：`api`（FastAPI）+ `worker`（Redis Stream 消费）+ `postgres` + `redis` + `web` + `nginx` 反代。

现状缺口（本 PRD 要解决的）：

1. **无认证**：`/api/jobs`、`/api/media` 任何人可调用。
2. **无限流**：nginx 仅反代；应用层无限流。
3. **无配额**：建任务、上传、在跑任务数均无上限。
4. `/storage` 用 `StaticFiles` 公开，知道路径即可下载任意文件。
5. CORS `allow_methods=["*"]` + `allow_credentials=True` 偏宽。
6. compose 将 `postgres`/`redis` 端口直接映射到宿主机，默认密码、Redis 无密码。
7. `model_name` 为前端自由字符串，未做白名单。
8. 上传文件仅靠 `content_type`（客户端可伪造）判断类型。

worker 关键事实：`worker/app/main.py` 的 `worker_loop` 是 `count=1` **单条顺序消费**，因此「并发控制」体现在 **队列深度背压** 与 **每用户在跑任务数**，而非 worker 内部线程并发。

---

## 1. 范围与分批交付

分 3 批，**按批合并、按批可上线**。每批末尾有「Docker 影响」说明。

| 批次 | 内容 | 是否改 Python 代码 | Docker |
|---|---|---|---|
| Phase 1 | nginx 限流 + compose 收紧 + CORS 收紧 | 否（仅配置） | **不重打镜像**，`docker compose up -d` 重建容器 |
| Phase 2 | API Key 认证 + 应用层限流 + model_name 白名单 + 文件 magic-bytes 校验 | 是（仅 `api`） | **只重打 `api`**：`docker compose build api` |
| Phase 3 | 配额（日任务数 / 存储总量 / 在跑任务数）+ 队列背压 + `/storage` 鉴权 | 是（`api`，可能动 `worker`） | 重打动到的服务 |

非目标（本期不做）：完整用户系统 / 登录页 / 计费 / 多租户隔离。API Key 即为「身份」。

---

## 2. Phase 1 — 零代码加固（配置层）

### 2.1 nginx 限流

文件：`infra/nginx.conf`

要求：
- 在 `http` 作用域定义限流区（注意：当前文件只有 `server {}` 块，需要把 zone 定义放到 nginx 主配置的 `http` 块。若 `infra/nginx.conf` 是被 `include` 进 `http` 的 server 片段，则新增一个 `infra/nginx-http.conf` 放 zone，并在 compose 挂载；实现时二选一，保持可运行）。
- 限流规则：
  - 全局 API：`limit_req_zone $binary_remote_addr zone=api_rl:10m rate=20r/s;`，在 `location /api/` 内 `limit_req zone=api_rl burst=40 nodelay;`
  - 上传/建任务（写操作）更严：对 `location = /api/media`、`location = /api/jobs` 单独 `limit_req zone=api_write burst=5 nodelay;`，`zone=api_write rate=2r/s`
  - 连接数：`limit_conn_zone $binary_remote_addr zone=api_conn:10m;`，`location /api/` 内 `limit_conn api_conn 10;`
- 对 WebSocket（`/api/ws/`）**不要**套写限流，仅保留现有 `proxy_read_timeout 3600s`。
- 把 `client_max_body_size` 从 `1024m` 调整为与应用一致：`client_max_body_size 512m;`（见 §2.3）。
- 返回码：限流命中返回 `429`（`limit_req_status 429; limit_conn_status 429;`）。

验收：
- `ab`/`wrk` 对 `/api/jobs` 持续压测，超出 burst 后稳定返回 `429`。
- WebSocket 长连接不受影响。

### 2.2 compose 收紧

文件：`docker-compose.yml`、`.env.example`、`.env`

要求：
- 生产配置移除 `postgres` 与 `redis` 的 `ports:` 宿主机映射（仅容器内网互通）。保留开发用映射时，新增 `docker-compose.override.yml`（dev 用）承载 `ports`，主 compose 不暴露。
- Redis 启用密码：command 改为 `["redis-server","--appendonly","yes","--requirepass","${REDIS_PASSWORD}"]`，`REDIS_URL` 改为 `redis://:${REDIS_PASSWORD}@redis:6379/0`。
- Postgres 密码：`.env.example` 中 `POSTGRES_PASSWORD` 改为占位符 `change_me_in_prod`，并在 README/注释强调生产必须覆盖。
- 给 `api`、`worker` 增加资源限制（compose v2 `deploy.resources.limits` 或 `mem_limit`/`cpus`），示例：`api` mem 1g、`worker` mem 4g（GPU/推理重）。具体值留可调。
- `api` 启动命令的 uvicorn 增加 `--workers 2`（按 CPU 调整），保持 `alembic upgrade head` 先于 uvicorn。
- `.env` 不进 git（确认 `.gitignore` 已含 `.env`；当前仓库 `.env` 已存在，需改为占位符或从版本库移除并仅保留 `.env.example`）。

验收：`docker compose config` 通过；`redis-cli` 无密码连接被拒；宿主机 `psql -h localhost` 在生产 compose 下连不上。

### 2.3 CORS 收紧

文件：`api/app/main.py`、`api/app/core/config.py`

要求：
- `cors_origins` 从环境变量读取（`config.py` 已有 `cors_origins` 字段，确认从 `CORS_ORIGINS` 注入）。生产值为真实域名，不含 `*`。
- `allow_methods` 由 `["*"]` 收紧为 `["GET","POST","DELETE","OPTIONS"]`。
- `allow_headers` 由 `["*"]` 收紧为 `["Authorization","Content-Type","X-API-Key"]`（为 Phase 2 预留）。
- `max_upload_mb` 默认值与 nginx `client_max_body_size` 对齐（均 512）。

验收：跨域非白名单 origin 的预检被拒。

---

## 3. Phase 2 — 认证 / 限流 / 输入加固（改 `api` 代码）

### 3.1 新增依赖

文件：`api/requirements.txt` 追加：
```
slowapi==0.1.9
```
（限流用。magic-bytes 校验用标准库 `mimetypes` + 自写魔数表，避免引入 `python-magic` 的系统库依赖。）

### 3.2 API Key 认证

新增文件：`api/app/core/security.py`

要求：
- 配置项（`config.py` 新增）：`api_keys: list[str]`（从 `API_KEYS` 注入，逗号或 JSON 列表），`auth_enabled: bool = True`。
- 提供 FastAPI 依赖 `require_api_key(x_api_key: str = Header(...))`：
  - `auth_enabled=False` 时直接放行（便于本地/测试）。
  - key 不在 `api_keys` 集合 → 抛 `HTTPException(401, "Invalid API key")`。
  - 返回一个稳定的 **caller 标识**（用 key 本身的 sha256 前 16 位作为 `client_id`），供限流/配额按身份计数。
- 健康检查 `/api/health` **不**需要 key。
- 写接口（`POST /api/media`、`POST /api/jobs`）与读接口（`GET /api/jobs*`）均挂 `Depends(require_api_key)`。把 `client_id` 通过依赖返回值传入路由。

文件改动：
- `api/app/api/routes/jobs.py`、`media.py`：在路由签名加 `client_id: str = Depends(require_api_key)`。
- `.env.example` 增加 `API_KEYS=devkey1,devkey2` 与 `AUTH_ENABLED=true`。

验收：无 `X-API-Key` 头访问 `POST /api/jobs` 返回 401；带合法 key 返回 201。

### 3.3 应用层限流（slowapi，Redis 后端）

新增文件：`api/app/core/ratelimit.py`

要求：
- 用 `slowapi.Limiter`，`key_func` 返回 §3.2 的 `client_id`（无 key 时回退到 `get_remote_address`）。
- storage 使用 Redis（`settings.redis_url`），保证多实例一致。
- 在 `api/app/main.py` 注册 `app.state.limiter` 与 `SlowAPIMiddleware`、`RateLimitExceeded` 处理器（返回 429 + `Retry-After`）。
- 装饰具体路由：
  - `POST /api/jobs`：`@limiter.limit("10/minute")`
  - `POST /api/media`：`@limiter.limit("20/minute")`
  - `GET` 列表/详情：`@limiter.limit("120/minute")`
- 注意 slowapi 要求被装饰的路由函数签名含 `request: Request`，需相应调整。

验收：同一 key 1 分钟内第 11 次建任务返回 429。

### 3.4 model_name 白名单

文件：`api/app/schemas.py`（`JobCreate`）、`api/app/api/routes/jobs.py`

要求：
- 配置项 `allowed_models: list[str]`（`ALLOWED_MODELS`，默认 `["best.pt"]`）。
- `create_job` 中校验 `data.model_name in settings.allowed_models`，否则 `HTTPException(422, "Unsupported model")`。
- 理由：`model_name` 透传到 `worker/app/main.py` 用于定位权重，必须防路径注入（拒绝含 `/`、`..` 的值）。

验收：`model_name="../etc/passwd"` 返回 422。

### 3.5 上传文件 magic-bytes 校验

文件：`api/app/services/storage.py`

要求：
- 在 `save_upload` 读取首个 chunk 后，校验文件头魔数与 `content_type` 声明的类别一致：
  - JPEG `FF D8 FF`、PNG `89 50 4E 47`、WEBP `RIFF....WEBP`、BMP `42 4D`
  - MP4/MOV `....ftyp`、MKV/WebM `1A 45 DF A3`、AVI `RIFF....AVI `
- 不匹配 → `HTTPException(415, "File content does not match declared type")`，并删除已落盘的临时文件。
- 保留现有 size 限制逻辑（`max_upload_mb`）。

验收：把 `.exe` 改名 `.jpg` 上传被拒 415。

**Phase 2 Docker**：仅改 `api` 代码与依赖 → `docker compose build api && docker compose up -d api`。其余服务不动。

---

## 4. Phase 3 — 配额 / 背压 / 存储鉴权

### 4.1 配额（Redis 计数器，按 client_id）

新增文件：`api/app/services/quota.py`

要求三类配额（值走配置，给默认）：

1. **日任务数** `QUOTA_JOBS_PER_DAY=200`
   - Redis key：`quota:jobs:{client_id}:{YYYYMMDD}`，`INCR` 后首次置 `EXPIRE` 到当日 24:00（或固定 86400s）。
   - 注意：脚本里禁止用本地随机/时钟生成日期键以外的随机性；日期取 UTC `date`（worker/api 用 `datetime.now(tz=UTC)`，此为应用代码非 workflow 脚本，可正常用时间）。
2. **存储总量** `QUOTA_STORAGE_MB=10240`
   - 上传成功后 `INCRBY quota:storage:{client_id}` 累加 `file_size`；建议同时落 PG 便于审计（可选）。
   - 超限在 `upload_media` 入口预估拒绝（用已知 `file_size` 不可得，故先落盘后校验：超限则删除文件并回滚计数，返回 413）。
3. **在跑任务数** `QUOTA_CONCURRENT_JOBS=3`
   - 建任务前查该 client_id 处于 `queued`/`running` 的任务数（PG 查询 `detection_jobs` join 一个新增的归属字段，见 §4.3），≥ 上限返回 `429 "Too many active jobs"`。

校验位置：
- `POST /api/media`：存储总量。
- `POST /api/jobs`：日任务数 + 在跑任务数。

返回体：统一 `{"detail": "...", "quota": {"limit": N, "used": M, "reset_at": "..."}}`，HTTP 429（速率/并发）或 413（存储）。

### 4.2 队列背压

文件：`api/app/api/routes/jobs.py`、`api/app/services/queue.py`

要求：
- 建任务前检查 Redis Stream 待处理长度：`XLEN(job_stream)` 或未 ack 的 pending 数。
- 超过 `QUEUE_MAX_DEPTH=500` 时拒绝新任务，返回 `503 "System busy, retry later"` + `Retry-After`。
- 目的：worker 单条顺序消费，必须防止队列无限堆积。

### 4.3 任务归属（配额前提）

数据库变更（Alembic 迁移，新增 `api/alembic/versions/0002_*.py`）：
- `detection_jobs` 增列 `client_id VARCHAR(64) NULL`（带 index）。
- `media_assets` 增列 `client_id VARCHAR(64) NULL`（带 index）。
- `create_job` / `upload_media` 写入 `client_id`。
- §4.1 的「在跑任务数」按 `client_id` 过滤统计。

> 迁移要求：可前向（`upgrade`）可回滚（`downgrade`）；老数据 `client_id` 允许为 NULL。

### 4.4 /storage 鉴权（择一实现，默认方案 A）

**方案 A（推荐，改动小）**：取消 `app.mount("/storage", StaticFiles(...))` 的公开挂载，改为受保护下载路由 `GET /api/files/{path}`：
- 挂 `require_api_key`；
- 仅允许下载 `client_id` 拥有的资源（按 `media_assets.storage_path` / `detection_jobs.result_path` 反查归属）；
- 用 `FileResponse` 返回，路径需做 traversal 防护（`Path(...).resolve()` 必须位于 `storage_root` 内）。
- 同步更新 `nginx.conf`：`/storage/` 反代去除或改指 `/api/files/`；更新 `web` 里拼接结果 URL 的地方（`result_url`、`url` 字段生成逻辑在 `jobs.py`/`media.py`）。

**方案 B（签名 URL）**：保留 StaticFiles，但下发带 HMAC 签名 + 过期时间的临时 URL，nginx/应用校验签名。改动大，本期默认不选。

验收（方案 A）：未带 key 访问结果文件 404/401；A 用户无法下载 B 用户的 `result_path`。

**Phase 3 Docker**：改 `api`（+ 可能 `worker` 若动到归属写入）→ 重打对应镜像并 `alembic upgrade head`（api 启动命令已含）。

---

## 5. 配置项汇总（统一加入 `config.py` 与 `.env.example`）

| 变量 | 默认 | 用途 |
|---|---|---|
| `AUTH_ENABLED` | `true` | 总开关 |
| `API_KEYS` | `devkey1` | 合法 key 列表 |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | 跨域白名单 |
| `ALLOWED_MODELS` | `["best.pt"]` | 模型白名单 |
| `MAX_UPLOAD_MB` | `512` | 单文件上限 |
| `REDIS_PASSWORD` | （空，生产必填） | Redis 密码 |
| `QUOTA_JOBS_PER_DAY` | `200` | 日任务配额 |
| `QUOTA_STORAGE_MB` | `10240` | 存储配额 |
| `QUOTA_CONCURRENT_JOBS` | `3` | 在跑任务并发 |
| `QUEUE_MAX_DEPTH` | `500` | 队列背压阈值 |

---

## 6. 测试要求

`api/tests/` 下新增/补充（pytest）：
- `test_auth.py`：无 key 401、错误 key 401、正确 key 通过、health 免认证。
- `test_ratelimit.py`：超频返回 429（可用 fakeredis 或 monkeypatch limiter）。
- `test_quota.py`：日任务数 / 在跑任务数 / 存储超限分别命中。
- `test_upload_validation.py`：伪造扩展名被拒 415、超大文件 413。
- `test_model_whitelist.py`：非法 model_name 422、路径注入 422。

CI/本地：`pytest api/tests` 全绿；`docker compose build api` 成功；`docker compose up -d` 后 `GET /api/health` 200。

---

## 7. 交付与回归检查清单

- [ ] Phase 1：nginx 限流生效（429）、pg/redis 不对外、Redis 有密码、CORS 收紧。
- [ ] Phase 2：API Key 生效、应用限流生效、model_name 白名单、magic-bytes 校验。
- [ ] Phase 3：三类配额生效、队列背压生效、`/storage` 鉴权、Alembic 迁移可升可回滚。
- [ ] 文档：更新 `README.md` 的部署/环境变量章节，新增「鉴权与配额」说明。
- [ ] 不破坏现有 WebSocket 实时日志（`/api/ws/`）与前端联调。

---

## 8. 给实现者的注意点（避免踩坑）

1. slowapi 装饰的路由函数**必须**含 `request: Request` 参数，否则报错。
2. `get_redis()`（`api/app/services/queue.py`）当前每次新建连接并 `aclose()`；限流/配额高频访问建议复用连接池，新增 `get_redis_pool()` 并在 app 生命周期内复用，避免连接风暴。
3. `client_id` 用「key 的 sha256 前缀」而非明文 key，避免明文写进日志/DB。
4. 方案 A 改 `/storage` 后，**前端拼 URL 的地方要一起改**（`job_to_schema` 的 `result_url`、`upload_media` 的 `url`）。
5. Alembic 迁移在 `api` 容器启动时自动执行（Dockerfile CMD 已含 `alembic upgrade head`），无需手动；但回滚需手动 `alembic downgrade -1`。
6. 配额计数与实际写库要尽量同一事务边界内或具备回滚（如存储超限需删文件 + 回退 Redis 计数），避免计数泄漏。
