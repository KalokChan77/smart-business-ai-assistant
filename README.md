# 东软智慧商务 AI 助手平台

[![CI](https://github.com/18and02/smart-business-ai-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/18and02/smart-business-ai-assistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

本地教学演示项目：**Vue3 前端 + FastAPI 后端 + LangGraph Agent + 独立 Dify 自托管**。

浏览器只访问 Vue3 与 FastAPI；DeepSeek / 百炼 / Dify 密钥仅保存在服务端 `.env`。

## 架构（本地）

```text
浏览器
  -> Vue3 (127.0.0.1:5173)
      -> FastAPI (127.0.0.1:8000)
           -> PostgreSQL / Redis（业务，独立 Compose）
           -> DeepSeek / DashScope
           -> Dify（独立目录 dify-self-host，默认 18080）
```

业务栈与 Dify **分两套 Compose**，避免排错互相干扰。详见决策日志 `DEC-20260717-008`、`DEC-20260718-030`。

## 目录

| 路径 | 说明 |
|---|---|
| `frontend/` | Vue3 + TypeScript + Vite |
| `backend/` | FastAPI + SQLAlchemy + Alembic + LangGraph |
| `deploy/app-compose.yml` | 业务 PostgreSQL + Redis |
| `deploy/dify/` | Dify 1.15.0 的项目覆盖层，不包含 Dify 官方源码 |
| `scripts/` | 本地一键启动/停止/状态 |
| `project_docs/mock_knowledge/` | 可公开使用的教学模拟知识库 |
| `project_docs/` | API 契约、决策日志、实习日记与答辩材料 |

## 快速开始

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

Windows PowerShell 请使用 `.venv\Scripts\python.exe`，并把文档中的
`.venv/bin/python` 替换为对应路径。

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

跳过演示种子：`SKIP_DEMO_SEED=1 ./scripts/dev_up.sh`

## 验证

```bash
# 后端
cd backend && ../.venv/bin/pytest && ../.venv/bin/alembic check

# 前端
cd frontend && npm run typecheck && npm test && npm run build
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

项目代码与仓库内自有文档采用 [MIT License](LICENSE)。Dify 仍遵循其官方
仓库许可证，本项目不重新分发 Dify 源码。
