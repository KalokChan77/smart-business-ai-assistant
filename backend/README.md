# 智慧商务 AI 助手 · FastAPI 后端

Vue3 对应的服务端：认证、租户 RBAC、会话、AI SSE、LangGraph Agent、Dify 知识/文档/TTS、客服辅助与统计。

## Docker 运行（推荐交付方式）

根目录 `compose.yml` 会构建本目录的 `Dockerfile`，在容器启动时自动执行
Alembic 迁移、幂等初始化演示账号，再以非 root 用户启动 Uvicorn：

```bash
docker compose up -d --build --wait
docker compose logs -f backend
```

容器通过服务名 `postgres`、`redis` 访问依赖；知识文档保存在
`smart-business-ai_app_knowledge_data` 数据卷。本机 Python 环境仅用于开发和测试。

## Python 环境

固定 Python 3.12。项目根目录虚拟环境解释器为：

```text
.venv/bin/python
.venv\Scripts\python.exe  # Windows
```

## 安装

在项目根目录：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e './backend[dev]'
```

配置根目录 `.env`（参考 `.env.example`），至少包含 `DATABASE_URL`、`REDIS_URL`、`JWT_SECRET_KEY` 以及所需 AI/Dify 变量。

## 数据库与依赖

```bash
# 业务 PostgreSQL + Redis
docker compose --env-file .env -f deploy/app-compose.yml up -d

# 迁移
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/alembic check
```

## 演示账号

```bash
../.venv/bin/python scripts/bootstrap_demo_tenant.py
```

默认租户：`a1000000-0000-4000-8000-000000000001`  
账号：`demo-admin` / `demo-user` / `demo-cs` / `demo-decision`

## 本地启动

```bash
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows 直接启动后端时请使用兼容入口，确保异步 psycopg 使用 Selector 事件循环：

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m scripts.run_dev_server --port 18000
```

或使用根目录一键脚本：`./scripts/dev_up.sh`

Windows 推荐在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\dev_up.ps1
```

- Swagger：`http://127.0.0.1:8000/docs`
- 存活：`http://127.0.0.1:8000/api/v1/health`
- 就绪：`http://127.0.0.1:8000/api/v1/health/ready`

## 测试

```bash
cd backend
../.venv/bin/pytest
```

## 结构原则

- 路由保持轻量，只处理 HTTP 与状态码；
- 领域服务负责业务判断；
- 外部依赖通过端口（Protocol）与依赖注入接入；
- 按业务领域分包，避免全局 Service/Model 堆积。
