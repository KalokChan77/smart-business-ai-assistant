# 东软智慧商务 AI 助手平台技术方案指导文档（V0.3 需求基线稿）

> 文档定位：用于统一教学项目的技术边界、系统架构、模块职责、接口规范、实施范围和验收标准。  
> 当前状态：需求基线稿。已确认以本地单机测试成功为核心目标，每组独立部署 Dify，云服务器和域名部署作为加分项。

## 1. 项目目标

建设面向企业用户、客服人员、系统管理员和决策者的智慧商务 AI 助手平台，实现：

1. AI 智能对话：多轮对话、意图识别、工具调用、上下文记忆和流式输出。
2. 企业知识库问答：文档上传、切分索引、检索增强、答案引用与反馈。
3. 智能客服辅助：问题分类、推荐回复、人工确认、对话记录管理。
4. 语音能力：文字转语音作为核心交付，语音识别作为增强功能。
5. 智能分析：咨询量、问题分类、满意度和高频问题洞察。
6. AI 服务编排：通过 FastAPI 统一封装 DeepSeek、LangGraph 和 Dify。

## 2. 技术方案核心原则

### 2.1 统一入口

浏览器只能访问 Vue3 前端和 FastAPI API，不直接调用 DeepSeek、LangGraph 或 Dify。模型密钥、Dify API Key、提示词和内部工作流不得暴露到前端。

### 2.2 单一编排责任

- FastAPI：系统级编排、鉴权、权限、数据持久化、路由、限流、审计和统一异常处理。
- LangGraph：需要代码控制、状态管理、工具调用和多步骤决策的智能体流程。
- Dify：知识库管理、可视化低代码工作流、运营人员可配置的 AI 应用和语音能力。
- DeepSeek：底层大模型能力，通过统一模型适配器访问。

同一条业务流程只能有一个主要 AI 编排引擎，禁止 LangGraph 与 Dify 相互循环调用。

### 2.3 教学实现与集成交付分层

- 教学实验阶段：可以分别实现 LangChain + FAISS/Chroma RAG、LangGraph Agent、Dify 知识库与工作流。
- 最终集成阶段：必须确定一个正式知识库来源和一个主要编排入口，避免重复索引、重复切分和答案不一致。

### 2.4 先完成可验收闭环

优先完成“登录 -> 对话 -> AI 路由 -> 工具/知识检索 -> 流式回复 -> 记录落库 -> 用户反馈”的完整闭环，再扩展多 Agent、语音识别、文生图和 Kubernetes。

## 3. 总体架构

```mermaid
flowchart TB
    U["用户浏览器"] --> FE["Vue3 前端"]
    FE --> GW["Nginx / Ingress"]
    GW --> API["FastAPI 统一 API 层"]

    API --> AUTH["认证与 RBAC"]
    API --> BIZ["用户 / 客服 / 工单 / 分析服务"]
    API --> AIGW["AI Gateway"]
    API --> KBAPI["知识库连接器"]

    AIGW --> MODEL["DeepSeek 模型适配器"]
    AIGW --> GRAPH["LangGraph 智能体服务"]
    AIGW --> DIFY["Dify 应用 / 工作流 API"]

    GRAPH --> TOOLS["数据库查询 / 外部 API / 业务工具"]
    GRAPH --> KBAPI
    DIFY --> DIFYKB["Dify 知识库"]
    KBAPI --> DIFYKB

    AUTH --> PG["PostgreSQL"]
    BIZ --> PG
    API --> REDIS["Redis 缓存 / 限流 / 会话"]
    API --> OBJ["MinIO / S3 文档存储"]

    API --> OBS["日志 / Trace / 指标 / AI 运行审计"]
    GRAPH --> OBS
    DIFY --> OBS
```

## 4. 各技术组件职责

| 组件 | 主要职责 | 不应承担的职责 |
|---|---|---|
| Vue3 | 页面交互、角色工作台、对话流展示、文件上传、数据可视化 | 保存模型密钥、直接调用模型、决定核心 AI 路由 |
| FastAPI | API 契约、鉴权、RBAC、业务服务、AI 路由、流式输出、审计、数据持久化 | 在路由函数中堆积提示词和复杂 Agent 逻辑 |
| DeepSeek | 对话生成、结构化输出、工具调用所需的模型推理 | 直接访问业务数据库或暴露给浏览器 |
| LangGraph | 状态化 Agent、条件路由、工具调用、多步骤任务、人工确认节点 | 用户管理、文件管理、通用 CRUD、前端会话鉴权 |
| Dify | 知识库、可视化工作流、可运营配置的应用、TTS 等低代码能力 | 作为系统唯一用户中心或直接暴露所有管理权限 |
| PostgreSQL | 用户、角色、对话、消息、工单、反馈、AI 运行记录和配置版本 | 存储大文件正文或作为短期流式消息队列 |
| Redis | 缓存、限流、短期会话、任务状态、幂等键 | 长期业务数据的唯一存储 |
| MinIO/S3 | 上传文档、语音和生成文件的对象存储 | 结构化业务查询 |

## 5. 推荐 AI 路由策略

### 5.1 普通 AI 对话

`Vue3 -> FastAPI -> AI Gateway -> DeepSeek -> SSE -> Vue3`

适用于不需要工具和知识库的普通问答。

### 5.2 工具调用与业务查询

`Vue3 -> FastAPI -> LangGraph -> 业务工具 -> DeepSeek 组织答案 -> SSE`

适用于订单查询、客户信息查询、数据统计等必须访问受控业务工具的场景。

### 5.3 企业知识库问答

推荐最终交付以 Dify 知识库为正式知识源：

`Vue3 -> FastAPI -> 知识库连接器 -> Dify 检索/应用 -> 带引用答案`

LangGraph 如需使用企业知识，应调用统一的知识库连接器，不自行维护第二份正式索引。

### 5.4 智能客服辅助

`客户问题 -> LangGraph 分类 -> 知识检索/业务查询 -> 生成建议回复 -> 质检 -> 客服人工确认 -> 发送`

客服回复默认采用 Human-in-the-loop，不建议在教学项目中直接全自动发送。

### 5.5 Dify 工作流

适合以下场景：

- 知识库维护和检索测试；
- 运营人员可调整的提示词或工作流；
- TTS、摘要、报告生成等低风险能力；
- 快速验证新 AI 场景。

不建议用 Dify 重复实现已经由 LangGraph 管理的核心多 Agent 业务流程。

## 6. 前端模块

### 6.1 企业用户端

- 登录与个人中心；
- AI 对话；
- 知识库问答；
- 答案引用、复制、赞踩反馈；
- TTS 播放；
- 历史会话。

### 6.2 客服人员端

- 待处理咨询列表；
- 客户对话窗口；
- AI 问题分类；
- 推荐回复与人工编辑确认；
- FAQ 维护；
- 历史记录检索。

### 6.3 管理员端

- 用户与角色管理；
- 文档上传和知识库同步；
- 模型、提示词和工作流配置；
- AI 运行记录与失败记录；
- 评价数据与基础统计。

### 6.4 决策者端

- 咨询量趋势；
- 问题分类分布；
- 满意度与人工接管率；
- 高频问题和 AI 摘要卡片。

## 7. FastAPI 后端模块

建议按领域拆分：

```text
app/
  api/              # REST/SSE 路由
  core/             # 配置、安全、异常、日志
  auth/             # 登录、JWT、RBAC
  users/            # 用户与角色
  conversations/    # 会话与消息
  customer_service/ # 客服与工单
  knowledge/        # 文档与知识库连接器
  ai/
    gateway/        # 统一调用入口
    providers/      # DeepSeek 等模型适配器
    graphs/         # LangGraph 流程
    dify/           # Dify API 适配器
    prompts/        # 提示词模板与版本
    schemas/        # AI 统一请求/响应事件
  analytics/        # 指标与报表
  audit/            # AI Run、工具调用、审计日志
  db/               # SQLAlchemy 与迁移
```

原则：API 路由只负责参数校验和调用应用服务，不直接编写复杂提示词、数据库 SQL 或 Agent 图。

## 8. 核心数据模型

建议至少包含：

- `users`、`roles`、`user_roles`
- `conversations`、`messages`
- `ai_runs`、`ai_run_events`、`tool_calls`
- `knowledge_documents`、`knowledge_sync_jobs`
- `customer_tickets`、`reply_suggestions`
- `feedback`
- `model_configs`、`prompt_templates`、`prompt_versions`
- `audit_logs`

所有 AI 请求应记录 `request_id`、`conversation_id`、`run_id`、模型、耗时、Token 用量、调用路径、错误码和用户反馈。

## 9. API 与流式事件规范

建议统一使用 `/api/v1` 前缀：

- `/auth/*`
- `/users/*`
- `/conversations/*`
- `/ai/chat/stream`
- `/ai/agent/stream`
- `/knowledge/documents/*`
- `/knowledge/query`
- `/customer-service/*`
- `/analytics/*`
- `/admin/ai-config/*`

大模型输出优先使用 SSE。统一事件类型：

- `metadata`
- `token`
- `tool_call`
- `tool_result`
- `citation`
- `message_end`
- `error`

前端不依赖 DeepSeek、LangGraph 或 Dify 的原始响应格式，只依赖平台统一事件协议。

## 10. 安全与可靠性

1. 模型和 Dify 密钥只保存在服务端环境变量或密钥管理系统。
2. 实施 JWT/OAuth2、RBAC 和接口权限校验。
3. 上传文件限制格式、大小和数量，并进行恶意文件检查。
4. 工具调用采用白名单和 Pydantic 参数校验，禁止模型直接执行任意 SQL 或系统命令。
5. 对模型调用设置超时、重试、并发限制、熔断和降级回复。
6. 对提示词注入、越权检索、敏感信息泄露进行专项测试。
7. 对管理员修改模型配置、提示词和知识库的行为记录审计日志。
8. 对答案展示引用来源；无法确认时明确表达不确定性。

## 11. 测试与 AI 评估

### 11.1 常规测试

- 后端单元测试与 API 集成测试；
- 前端组件测试和关键流程 E2E 测试；
- 权限、异常、超时和并发测试；
- Docker Compose 启动与健康检查。

### 11.2 AI 专项评估

“AI 功能准确率不低于 80%”必须转化为可重复执行的测试集，建议建立至少 100 条标注样例，分别评估：

- 意图分类准确率；
- 工具选择准确率；
- 工具参数正确率；
- 知识检索命中率；
- 答案正确性与引用一致性；
- 客服回复可用率；
- 拒答和安全边界表现。

## 12. 分阶段实施范围

### 12.1 核心交付范围

1. Vue3 登录、角色工作台和基础管理页面；
2. FastAPI 鉴权、RBAC、会话和消息接口；
3. DeepSeek 流式对话；
4. LangGraph 单 Agent + 至少一个业务工具；
5. 企业知识库问答并展示引用；
6. 客服推荐回复和人工确认；
7. Dify TTS；
8. AI 运行日志、反馈和基础统计；
9. Docker Compose 一键启动。

### 12.2 增强范围

- 多 Agent 分类、查询、回复和质检；
- 语音识别输入；
- 文生图；
- 复杂智能分析报告；
- 模型自动降级；
- Kubernetes、Ingress 和完整 CI/CD。

## 13. 推荐部署拓扑

教学和验收环境优先使用 Docker Compose：

- `frontend`
- `backend`
- `postgres`
- `redis`
- `minio`（可选）
- `dify` 独立服务组

Kubernetes 作为增强教学内容，不作为核心功能完成的前置条件。Dify 依赖较多，建议与业务应用分开维护 Compose 配置，避免初学者一次性调试全部容器。

## 14. 当前需要统一的方案决策

建议采用以下默认结论：

1. **系统形态**：教学演示级、单企业租户，数据模型预留 `tenant_id`。
2. **主要 Agent 编排**：LangGraph。
3. **正式知识库**：Dify 知识库；FAISS/Chroma 用于课程实验，不作为最终双轨生产知识库。
4. **统一入口**：所有 AI 能力必须经过 FastAPI。
5. **模型策略**：DeepSeek 为主模型，通过 Provider Adapter 保留切换通义千问/OpenAI 兼容模型的能力。
6. **流式协议**：SSE；只有真正的双向实时客服场景才使用 WebSocket。
7. **核心部署验收**：Docker Compose；Kubernetes 为增强项。
8. **人工控制**：客服建议回复必须人工确认，敏感工具调用必须具备权限检查和审计。

## 15. 后续文档完善项

V0.2 建议继续补充：

1. 用例图和角色权限矩阵；
2. 核心业务时序图；
3. 数据库 ER 图；
4. API 请求/响应示例；
5. LangGraph State、节点和条件边定义；
6. Dify 应用清单及 API 对接规范；
7. 部署资源估算和环境变量清单；
8. 测试数据集、AI 评估表和验收 Checklist；
9. 12 天实施任务拆分和团队分工模板。


## 16. Python 依赖库与教学重点

### 16.1 原始清单规范化

原始资料中的 `sqlal chemy`、`pydantie` 和 `pumpy` 是拼写错误，正确包名分别为 `sqlalchemy`、`pydantic` 和 `numpy`。FastAPI 路由装饰器应写成 `@app.get("/")`，Uvicorn 热重载参数应写成 `--reload`。

| pip 安装包名 | Python 导入名 | 用途 | 教学重点 |
|---|---|---|---|
| `fastapi` | `fastapi` | Web API 框架 | `FastAPI()`、`@app.get()`/`@app.post()`、依赖注入、异常处理、自动 API 文档、流式响应 |
| `uvicorn[standard]` | `uvicorn` | ASGI 服务器，运行 FastAPI | `uvicorn app.main:app --reload`、host/port、开发热重载与生产运行的区别 |
| `sqlalchemy` | `sqlalchemy` | 数据库 Core 与 ORM | Declarative Model、`Mapped`、`mapped_column()`、Session、关系映射、事务；ORM 不能替代 SQL 基础 |
| `pydantic` | `pydantic` | 请求、响应和配置数据校验 | `BaseModel`、类型标注、`Field`、Validator、嵌套模型、`model_dump()`、校验错误 |
| `dashscope` | `dashscope` | 阿里云百炼 SDK | API Key 环境变量、通义千问调用、流式输出、Embedding、异常和限流处理 |
| `numpy` | `numpy` | 数值与向量计算 | ndarray、向量归一化、点积、余弦相似度；只有归一化后点积才等价于余弦相似度 |
| `python-multipart` | 通常不直接导入 | FastAPI 表单和文件上传解析 | `multipart/form-data`、`UploadFile`、文件大小/类型校验、临时文件处理 |
| `pypdf` | `pypdf` | PDF 文本解析 | `PdfReader`、逐页提取文本、页码元数据；扫描版 PDF 需要 OCR，不能仅依赖 pypdf |
| `python-docx` | `docx` | `.docx` Word 文档解析 | `Document`、段落、表格、标题层级；不负责旧版 `.doc` 文件解析 |

### 16.2 当前架构必须补充的依赖

原始清单可以支撑 FastAPI、数据库、百炼调用和基础文档解析，但无法完整实现需求中的 DeepSeek、LangGraph、Dify、缓存、数据库迁移和测试。

| pip 安装包名 | 用途 | 教学重点 | 是否核心 |
|---|---|---|---|
| `langchain` | 模型、Prompt、Tool、文档和检索抽象 | Model、Prompt、Tool、Runnable、结构化输出 | 核心 |
| `langgraph` | 状态化智能体和工作流编排 | State、Node、Edge、条件路由、Checkpoint、Human-in-the-loop | 核心 |
| `langchain-deepseek` | LangChain 的 DeepSeek 模型适配 | 模型初始化、流式输出、工具调用、Provider 解耦 | 核心 |
| `langchain-community` | 社区文档加载器和部分向量库集成 | Loader 的适用范围、第三方依赖边界 | 课程需要 |
| `faiss-cpu` 或 `chromadb` | RAG 实验向量存储 | 二选一完成课程实验，避免学生同时维护两套实验代码 | 课程需要 |
| `httpx` | 异步 HTTP 客户端 | 调用 Dify 和其他服务、连接池、超时、重试、流式响应 | 核心 |
| `redis` | Redis Python 客户端 | 缓存、限流、幂等、短期状态；不得作为长期业务数据唯一存储 | 核心 |
| `alembic` | SQLAlchemy 数据库迁移 | revision、upgrade、downgrade、版本化数据库结构 | 核心 |
| `psycopg[binary]` | PostgreSQL 驱动 | 数据库连接、连接池、事务；开发环境可使用 binary 发行包 | PostgreSQL 时核心 |
| `pydantic-settings` | 环境变量和配置管理 | `.env`、配置分环境、密钥不入库 | 核心 |
| `PyJWT[crypto]` | JWT 生成与验证 | access token、过期时间、签名验证、权限声明 | 核心 |
| `pwdlib[argon2]` | 密码哈希 | 不保存明文密码、哈希验证、算法配置 | 核心 |
| `sse-starlette` | SSE 响应辅助 | 事件类型、断线、心跳、结束事件；也可直接使用 FastAPI StreamingResponse | 推荐 |
| `pytest` | Python 测试框架 | 单元测试、Fixture、异常场景、AI Provider Mock | 核心 |
| `pytest-asyncio` | 异步代码测试 | FastAPI、HTTPX、异步模型调用测试 | 核心 |

### 16.3 Dify 对接方式

Dify 应优先通过 HTTP API 接入，因此不要求安装所谓“Dify Python SDK”。后端统一使用 `httpx.AsyncClient` 封装：

```text
app/ai/dify/client.py
app/ai/dify/schemas.py
app/ai/dify/exceptions.py
```

Dify API Key 必须保存在后端环境变量中，浏览器不能直接访问 Dify API。

### 16.4 推荐分组安装

为了降低首日环境搭建失败率，建议不要一次安装所有 AI 依赖，而是按教学阶段分组：

```bash
# 第一阶段：FastAPI 基础
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings python-multipart

# 第二阶段：数据库与安全
pip install alembic "psycopg[binary]" redis "PyJWT[crypto]" "pwdlib[argon2]"

# 第三阶段：大模型与智能体
pip install dashscope langchain langgraph langchain-deepseek langchain-community httpx

# 第四阶段：RAG 文档处理
pip install numpy pypdf python-docx faiss-cpu

# 第五阶段：测试
pip install pytest pytest-asyncio
```

如果课堂统一选择 Chroma，则将 `faiss-cpu` 替换为 `chromadb`。最终项目不应同时强制安装和使用 FAISS、Chroma、Dify 三套正式向量存储。

### 16.5 最小代码示例应采用的正确写法

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

开发环境启动：

```bash
uvicorn app.main:app --reload
```

`--reload` 只用于本地开发；容器或生产环境不使用热重载，并应根据部署资源配置进程和并发策略。


## 17. 已确认的项目约束与验收基线

根据当前沟通，以下内容从“待确认事项”调整为项目基线：

| 项目 | 已确认结论 | 对技术方案的影响 |
|---|---|---|
| 系统定位 | 教学实训、功能测试成功即可 | 不按大规模生产系统设计，不设置复杂高可用集群 |
| 并发规模 | 不要求大规模运行 | 优先保证完整链路、代码结构和异常处理，不进行分布式扩容 |
| API Key | 每组或个人自行配置 | 提供 `.env.example`，密钥不得写入代码或提交 Git |
| Dify | 每个小组自行本地部署 | 将 Dify 部署列为小组环境验收项，业务系统通过可配置 URL 调用 |
| 业务数据 | 预计由教师提供 | 在数据未下发前使用 Mock/种子数据，提供数据导入适配层 |
| 知识库文档 | 预计由教师提供 | 在正式文档下发前准备示例 PDF/DOCX，解析和索引流程不依赖具体内容 |
| 核心部署 | 本地部署 | Docker Compose 为核心验收方式，不强制 Kubernetes |
| 云端部署 | 自有 Oracle Cloud 服务器和域名 | 作为加分项，不阻塞本地核心验收 |

### 17.1 核心成功标准

本项目不以承载大规模用户为目标。核心成功标准为：

1. 新环境能够按照 README 完成安装和启动；
2. Vue3 能正常访问 FastAPI；
3. FastAPI 能通过环境变量调用配置的大模型；
4. LangGraph Agent 能完成至少一次真实工具调用；
5. Dify 能独立启动、创建应用或知识库，并能被 FastAPI 调用；
6. PDF/DOCX 能上传、解析、索引并完成知识问答；
7. AI 回复能够流式展示，并记录对话和运行状态；
8. 外部 API 不可用时能返回明确错误，而不是系统崩溃；
9. Docker Compose 停止后再次启动，核心数据仍然存在；
10. 按验收用例运行通过并完成项目演示。

### 17.2 明确不作为核心要求的能力

- 大规模并发和压力测试；
- Kubernetes 集群和自动扩缩容；
- 多机数据库和 Redis 高可用；
- 企业级灾备；
- 复杂消息队列集群；
- 完整零信任网络；
- 生产级多租户计费系统；
- 7x24 小时可用性承诺。

这些内容可以在技术方案中作为扩展说明，但不能占用核心功能实现时间。

## 18. 每组本地部署建议

### 18.1 分开维护两套 Compose

建议每组分别维护：

```text
project/
  deploy/
    app-compose.yml       # Vue3、FastAPI、PostgreSQL、Redis
  dify/                   # 官方 Dify 自托管目录或独立克隆目录
```

不建议初期直接把 Dify 的全部服务合并到业务项目 Compose。原因是 Dify 自身包含多个服务，合并后排错难度明显增加。

本地访问关系：

```text
浏览器 -> Vue3 -> FastAPI -> http://localhost:<dify-port>
                        -> DeepSeek / DashScope API
                        -> PostgreSQL / Redis
```

### 18.2 小组环境验收表

每组在正式开发前提交：

- 操作系统及版本；
- CPU 架构：x86_64 或 ARM64；
- Docker 和 Docker Compose 版本；
- Python 版本；
- Node.js 版本；
- Dify 首页截图；
- Dify 工作空间和测试应用；
- 大模型 API 连通测试结果；
- FastAPI `/health` 测试结果；
- 前端访问 FastAPI 的测试结果。

### 18.3 配置文件约定

项目提交：

```text
.env.example
```

个人本地使用：

```text
.env
```

至少包含：

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg://app:password@localhost:5432/app
REDIS_URL=redis://localhost:6379/0

LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DASHSCOPE_API_KEY=

DIFY_BASE_URL=http://localhost:5001
DIFY_APP_API_KEY=
DIFY_DATASET_API_KEY=

JWT_SECRET_KEY=replace-me
```

`.env`、数据库文件、上传文件和 Dify 本地数据目录不得提交到 Git。

## 19. 教师数据未下发前的处理方案

不能等待教师数据后才开始开发。建议先建立统一数据契约和示例数据：

### 19.1 模拟业务数据

至少提供：

- 20 个客户；
- 20 个产品或商务服务；
- 50 个订单；
- 30 个客服工单；
- 30 个 FAQ；
- 50 条历史咨询记录。

正式数据下发后，只替换数据导入脚本，不修改业务接口。

### 19.2 示例知识库

先准备少量自编或公开测试文档：

- 企业简介；
- 产品说明；
- 售后政策；
- 退款规则；
- 客服处理规范。

每份文档控制在易于调试的范围，确保能够人工判断检索结果是否正确。

### 19.3 数据导入边界

教师数据可能是 CSV、Excel、SQL 或 API，因此建议定义：

```text
scripts/import_seed_data.py
scripts/import_teacher_data.py
```

导入脚本负责格式转换，业务代码只依赖统一数据库模型。

## 20. Oracle Cloud 与域名加分方案

Oracle Cloud 服务器和域名可以作为明确的加分项，建议定义为“云端部署与公网演示能力”，不改变本地验收标准。

### 20.1 加分项分级

| 等级 | 内容 |
|---|---|
| 加分一级 | 将 Vue3、FastAPI、PostgreSQL、Redis 部署到 Oracle Cloud，公网 IP 可访问 |
| 加分二级 | 配置域名、Nginx 反向代理和 HTTPS |
| 加分三级 | 云端同时部署 Dify，完成公网端到端 AI 对话和知识库问答 |
| 加分四级 | 增加自动部署、备份、监控或 CI/CD |

### 20.2 推荐域名结构

```text
ai.example.com       -> Vue3 / FastAPI
api.example.com      -> FastAPI（可选，或统一使用 /api）
dify.example.com     -> Dify（加分项）
```

教学项目也可以只使用一个域名：

```text
example.com/         -> Vue3
example.com/api/     -> FastAPI
example.com/dify/    -> Dify（需要正确处理反向代理路径）
```

为了减少 Dify 子路径配置问题，更推荐为 Dify 使用独立子域名。

### 20.3 云端安全底线

- PostgreSQL 和 Redis 不向公网开放端口；
- 只开放 HTTP/HTTPS 和必要的 SSH；
- 使用 SSH Key，不使用弱密码；
- API Key 只保存在服务器环境变量；
- Dify 管理后台使用强密码；
- 配置 HTTPS；
- 云端部署前备份本地数据库和 Dify 数据卷；
- 域名和公网地址不写死在前端代码中。

### 20.4 上云前需要记录的服务器信息

在决定是否将 Dify 一起部署到 Oracle Cloud 前，需要确认：

```bash
uname -m
cat /etc/os-release
nproc
free -h
df -h
docker version
docker compose version
```

重点确认 CPU 架构、内存、磁盘和 Docker 环境。若资源不足，云端只部署业务应用，Dify 云端部署保留为更高等级加分项。

## 21. 调整后的实施优先级

```text
P0：本地开发环境、FastAPI、Vue3、数据库、大模型连通
P1：流式 AI 对话、会话持久化、异常处理
P2：LangGraph 工具调用
P3：每组 Dify 本地部署及 FastAPI 对接
P4：知识库上传、检索、引用与客服辅助
P5：Docker Compose、测试用例、README 和答辩演示
P6：Oracle Cloud、域名、HTTPS、CI/CD 等加分项
```

只有 P0 到 P5 全部通过后，才进入 P6，避免为了上云影响核心功能完成。
