# YOLO11 Detection Framework

一个可直接落地的 YOLO 检测 MVP 工程，提供从媒体上传、任务排队、异步推理到结果回传与前端展示的完整闭环。

这个仓库当前按单模型部署方式收敛：

- worker 固定读取 `models/best.pt`
- 本地运行和 Docker 运行使用同一套模型约定
- 不再需要配置 `YOLO_DEMO_MODE` 或 `YOLO_MODEL_PATH`

## 技术栈

- Frontend: Next.js App Router + TypeScript
- API: FastAPI + SQLAlchemy Async + Alembic
- Worker: Python + Ultralytics YOLO + OpenCV
- Queue: Redis Streams
- Database: PostgreSQL 16
- Runtime: Docker Compose

## 核心能力

- 上传图片或视频并创建检测任务
- 通过 Redis Streams 将任务分发给异步 worker
- 使用 YOLO 模型执行真实推理并保存结果
- 在前端查看任务状态、结果图/视频和任务日志
- 使用 Docker Compose 一键启动整套服务

## 模型约定

项目固定从 `models/best.pt` 读取模型：

- 本地直接运行时，读取的是仓库根目录下的 `models/best.pt`
- `docker compose up --build` 时，worker 镜像会把 `models/` 目录打包进镜像
- 本地 `docker compose` 运行时，`./models` 也会挂载到容器 `/app/models`

切换模型时，只需要替换 `models/best.pt`。

如果 `models/best.pt` 不存在，worker 会直接报错并提示补齐模型文件。

## 目录结构

```text
api/            FastAPI 服务、数据库模型、任务接口、WebSocket 事件
worker/         Redis Streams worker、YOLO/OpenCV 推理逻辑
web/            Next.js 前端控制台
infra/          部署示例文件
models/         YOLO 权重目录（固定使用 best.pt，默认不提交）
storage/        上传文件与检测结果目录
docker-compose.yml
MODEL_USAGE.md
```

## 快速开始

### 1. 准备模型

将你的训练权重放到：

```text
models/best.pt
```

### 2. 准备环境文件

如果仓库根目录还没有 `.env`：

```powershell
Copy-Item .env.example .env
```

### 3. 启动整套服务

在仓库根目录执行：

```powershell
docker compose up --build
```

启动后访问：

- Frontend: `http://localhost:3000`
- API Docs: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/api/health`

## 常用命令

```powershell
docker compose up
docker compose up --build
docker compose logs -f worker
docker compose logs -f api
docker compose down
docker compose build worker
```

仅替换 `models/best.pt` 且不改代码时，通常只需要：

```powershell
docker compose up
```

如果修改了 worker 代码或想把最新模型重新打进镜像：

```powershell
docker compose build worker
docker compose up
```

## 开发说明

- `.env` 已加入 `.gitignore`，不会提交本地配置
- `models/` 默认不提交，只保留 `.gitkeep`
- `storage/uploads` 和 `storage/results` 默认不提交运行产物
- worker 单元测试位于 `worker/tests/test_config.py`

## 当前项目状态

这个仓库当前已经收敛为适合演示与部署的单模型版本，重点在于：

- 完整业务链路可运行
- 模型使用约定简单稳定
- Docker 打包与本地运行方式一致

如需更多模型管理能力，建议在此基础上单独扩展，而不是重新引入路径开关和演示模式。
