# 东软智慧商务 AI 助手平台

[![CI](https://github.com/KalokChan77/smart-business-ai-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/KalokChan77/smart-business-ai-assistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

本地教学演示项目：**Vue3 前端 + FastAPI 后端 + LangGraph Agent + 独立 Dify 自托管**。

浏览器只访问 Vue3 与 FastAPI；DeepSeek / 百炼 / Dify 密钥仅保存在服务端 `.env`。

## 架构（完整容器模式）

```text
浏览器
  -> Nginx + Vue3 容器 (127.0.0.1:5173)
      -> FastAPI 容器 (容器内 8000；本机 127.0.0.1:18000)
           -> PostgreSQL / Redis 容器（内部服务名访问）
           -> DeepSeek / DashScope
           -> Dify（独立 Docker 栈，默认通过 host.docker.internal:18080）
```

完整业务栈由根目录 `compose.yml` 统一管理；Dify 仍使用独立 Compose，避免升级
和排错互相干扰。业务数据库、Redis 与知识文档分别使用命名数据卷。

## 目录

| 路径 | 说明 |
|---|---|
| `compose.yml` | 完整业务栈：前端、后端、PostgreSQL、Redis |
| `frontend/` | Vue3 + TypeScript + Vite |
| `backend/` | FastAPI + SQLAlchemy + Alembic + LangGraph |
| `frontend/Dockerfile` | Vue 构建阶段 + Nginx 运行镜像 |
| `backend/Dockerfile` | Python 3.12 FastAPI 运行镜像 |
| `deploy/app-compose.yml` | 仅供本机开发模式使用的 PostgreSQL + Redis |
| `deploy/dify/` | Dify 1.15.0 的项目覆盖层，不包含 Dify 官方源码 |
| `scripts/` | 本地一键启动/停止/状态 |
| `project_docs/mock_knowledge/` | 可公开使用的教学模拟知识库 |
| `project_docs/` | API 契约、决策日志、实习日记与答辩材料 |

## 快速开始

### 完整 Docker 模式（Windows / macOS 推荐）

另一台电脑只需要安装 Docker Desktop，不需要单独安装 Python、Node.js、
PostgreSQL 或 Redis。首次复制环境文件并修改其中的密码和密钥：

前端与后端镜像均已实际完成 `linux/amd64` 和 `linux/arm64` 构建验证，适用于
常见 Windows Docker Desktop、Intel Mac 与 Apple Silicon Mac 环境。

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

至少替换 `.env` 中的 `APP_POSTGRES_PASSWORD`、`APP_REDIS_PASSWORD`、
`JWT_SECRET_KEY` 和 `DEMO_PASSWORD`。需要 AI 功能时再填写 DeepSeek、百炼和
Dify Key。密码建议使用 URL 安全字符，避免在数据库连接串中转义。

在项目根目录构建并启动全部四个服务：

```bash
docker compose up -d --build --wait
docker compose ps
```

启动后访问：

- 前端：http://127.0.0.1:5173
- API 文档：http://127.0.0.1:18000/docs
- 就绪检查：http://127.0.0.1:5173/api/v1/health/ready

查看日志或停止服务：

```bash
docker compose logs -f backend frontend

# 停止并删除容器、网络，保留数据卷和镜像
docker compose down

# 完全删除该业务栈的容器、网络、数据卷和相关镜像
docker compose down -v --rmi all --remove-orphans
```

Docker Desktop 的 **Containers** 页面会显示一个 `smart-business-ai` 项目组，
其中包含 `frontend`、`backend`、`postgres`、`redis`。可在界面停止或删除项目；
若删除对话框没有勾选数据卷，还需在 **Volumes** 页面删除
`smart-business-ai_app_postgres_data`、`smart-business-ai_app_redis_data` 和
`smart-business-ai_app_knowledge_data`。镜像在 **Images** 页面单独管理。

完整 Docker 模式和下面的本机开发模式不能同时占用同一组端口。切换到本机
开发前先执行 `docker compose down`。

### Windows 本机开发（备用）

本项目已提供原生 PowerShell 脚本，不需要 Git Bash，也不需要手工把
`.venv/bin` 改成 `.venv\Scripts`。

准备 Python 3.12、后端虚拟环境、前端依赖和本地 `.env`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

首次运行前打开 Docker Desktop，确认左下角显示 Engine running，然后启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev_up.ps1
```

首次会提示输入四个演示账号共用的本地密码（至少 8 位）。脚本会依次启动
PostgreSQL、Redis、执行迁移、初始化账号，并在后台启动 FastAPI 与 Vue。
本机 Windows 默认使用前端 `5173`、后端 `18000`；这是为了避开常被系统进程
PID 4 保留的 `8000`。可在 `.env` 修改 `APP_FRONTEND_PORT` 和
`APP_BACKEND_PORT`，也可在启动时传入 `-FrontendPort` / `-BackendPort`。

```powershell
# 查看状态
powershell -ExecutionPolicy Bypass -File .\scripts\dev_status.ps1

# 停止前后端；数据库和 Redis 默认保留
powershell -ExecutionPolicy Bypass -File .\scripts\dev_down.ps1

# 连数据库和 Redis 一并停止
powershell -ExecutionPolicy Bypass -File .\scripts\dev_down.ps1 -StopData
```

`setup_windows.ps1` 首次创建 `.env` 时会随机生成本地数据库、Redis 和 JWT
密钥；已有 `.env` 永远不会被覆盖。DeepSeek、百炼和 Dify Key 仍需按实际使用
情况手工填写，未填写时基础登录、管理和本地业务页面仍可启动。

Windows 启动后的地址：

- 前端：http://127.0.0.1:5173
- API 文档：http://127.0.0.1:18000/docs
- 就绪检查：http://127.0.0.1:18000/api/v1/health/ready

### macOS / Linux 本机开发（备用）

### 1. 准备环境

- Python 3.12
- Node.js `20.19+` 或 `22.12+`（含 npm，符合 Vite 8 要求）
- Docker / Docker Compose

```bash
# Python 虚拟环境（项目根目录）
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e './backend[dev]'

# 前端依赖
cd frontend && npm ci && cd ..

# 环境变量（不要提交 .env）
cp .env.example .env
# 编辑 .env：填写 DATABASE/REDIS 密码、JWT、DeepSeek/百炼、Dify 三类 Key 等
chmod 600 .env
```

### 2. 启动 Dify（独立，首次需要）

```bash
git clone --branch 1.15.0 --depth 1 https://github.com/langgenius/dify.git dify-self-host
cd dify-self-host/docker
cp .env.example .env
```

在 Dify `.env` 中设置强随机密码，并将本地端口设为 `18080`、`18443`、
`15003`。随后按 [`deploy/dify/README.md`](deploy/dify/README.md) 应用 Jieba
和共享存储覆盖层并启动。

默认对外：`http://127.0.0.1:18080`。三类 API Key 与 Dataset 配置见
[`project_docs/Dify三个Key配置指南.md`](project_docs/Dify三个Key配置指南.md)。

若 Nginx 在 API 容器重建后出现 502，可重启 Dify 的 Nginx 容器使上游地址刷新。

### 3. 一键启动业务开发栈

```bash
./scripts/dev_up.sh
```

Windows 使用前面的 `scripts/dev_up.ps1`。

未设置 `DEMO_PASSWORD` 时会安全提示输入，不会回显或写入仓库。需要固定
租户 ID 时可设置 `DEMO_TENANT_ID`。

脚本会：

1. 启动业务 PostgreSQL / Redis（`deploy/app-compose.yml`）  
2. 执行 `alembic upgrade head`  
3. 幂等初始化四角色演示账号  
4. 后台启动 FastAPI（8000）与 Vite（5173）

访问：

- 前端：http://127.0.0.1:5173  
- API 文档：http://127.0.0.1:8000/docs  
- 就绪检查：http://127.0.0.1:8000/api/v1/health/ready  

停止开发进程：

```bash
./scripts/dev_down.sh
# 同时停止业务数据库/缓存：
STOP_DATA=1 ./scripts/dev_down.sh
```

状态检查：

```bash
./scripts/dev_status.sh
```

Windows 使用 `scripts/dev_status.ps1` 与 `scripts/dev_down.ps1`。

### 4. 演示账号（本地教学）

默认演示租户 ID：

```text
a1000000-0000-4000-8000-000000000001
```

| 用户名 | 角色 | 默认落地页 |
|---|---|---|
| `demo-admin` | 管理员 | `/admin/overview` |
| `demo-user` | 企业用户 | `/app/chat` |
| `demo-cs` | 客服 | `/service/tickets` |
| `demo-decision` | 决策者 | `/decision/overview` |

共享密码由你在 `DEMO_PASSWORD` 或交互提示中设置；**不会打印到日志，也不写入 Git**。

单独初始化/重置：

```bash
.venv/bin/python backend/scripts/bootstrap_demo_tenant.py
# 强制覆盖已有密码：
.venv/bin/python backend/scripts/bootstrap_demo_tenant.py --reset-password
```

Windows 对应命令为：

```powershell
.\.venv\Scripts\python.exe .\backend\scripts\bootstrap_demo_tenant.py
.\.venv\Scripts\python.exe .\backend\scripts\bootstrap_demo_tenant.py --reset-password
```

跳过演示种子：`SKIP_DEMO_SEED=1 ./scripts/dev_up.sh`

## 验证

```bash
# 后端
cd backend && ../.venv/bin/pytest && ../.venv/bin/alembic check

# 前端
cd frontend && npm run typecheck && npm test && npm run build
```

Windows PowerShell：

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\python.exe -m alembic check
Pop-Location

Push-Location frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
Pop-Location
```

## 文档

- 技术方案：`东软智慧商务AI助手平台-技术方案指导文档-V0.3需求基线稿.md`
- API 清单：`project_docs/系统内部API清单-V0.1.md`
- 答辩演示：`project_docs/答辩演示流程-V0.1.md`
- 决策日志：`project_docs/决策日志/`
- 实习日记：`project_docs/实习日记/`
- 后端说明：`backend/README.md`
- 前端说明：`frontend/README.md`

## 模拟数据

仓库保留 `project_docs/mock_knowledge/` 中的企业客服、产品套餐、退款售后、
知识文档和账户安全模拟资料，以及 `project_docs/模拟验收问题集.csv`。这些内容
只用于教学、开发和测试，不代表任何真实企业政策或客户数据。

## 安全约定

- 禁止将真实 API Key、密码、JWT、Cookie、Dataset ID 写入代码、测试、决策日志或 README；
- `.env` 与 `project_docs/key env/` 已在 `.gitignore`；
- 浏览器只持有当前会话令牌；模型与 Dify 凭据仅服务端使用。

发现安全问题请阅读 [`SECURITY.md`](SECURITY.md)，不要在公开 Issue 中粘贴密钥。

## 当前阶段与后续

已完成：认证与 RBAC、会话、AI SSE、LangGraph Agent、Dify 知识与文档、客服人工确认、TTS、统计、Vue3 四角色工作台、本地一键启动、演示账号初始化与答辩演示流程。

后续：答辩前计时彩排；可选 Oracle Cloud + 域名公网部署（P6 加分项）。

## 许可证

本仓库基于 [18and02/smart-business-ai-assistant](https://github.com/18and02/smart-business-ai-assistant)
的 MIT 许可版本进行二次开发，保留原始提交历史与许可证声明；本仓库新增完整容器化、
Windows 本地运行支持及相关文档与验证配置。

项目代码与仓库内自有文档采用 [MIT License](LICENSE)。Dify 仍遵循其官方
仓库许可证，本项目不重新分发 Dify 源码。
