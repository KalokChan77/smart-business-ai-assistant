# 需要提供的 API 与环境信息清单

> 不要把 API Key、服务器密码或 SSH 私钥直接发送到聊天中。后续请把 API Key 填入项目本地 `.env` 文件；只需要告诉开发人员已配置了哪些变量。

## 1. DeepSeek

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_CHAT_MODEL=
```

需要确认：

- 是否已经开通 API；
- Chat 模型名称；
- 是否允许流式输出；
- 账户是否有可用额度。

## 2. 阿里云百炼 DashScope

```dotenv
DASHSCOPE_API_KEY=
DASHSCOPE_CHAT_MODEL=
DASHSCOPE_EMBEDDING_MODEL=
DASHSCOPE_TTS_MODEL=
DASHSCOPE_ASR_MODEL=
```

其中 Chat 为主要或备用对话模型，Embedding 用于课程 RAG 实验，TTS 为核心语音加分功能，ASR 可以后补。

## 3. Dify

```dotenv
DIFY_BASE_URL=http://localhost:5001
DIFY_CHAT_APP_API_KEY=
DIFY_WORKFLOW_API_KEY=
DIFY_DATASET_API_KEY=
DIFY_USER_PREFIX=team01
```

需要准备：

- 本地 Dify 访问地址；
- 一个 Chatflow/Agent 应用；
- 一个 Workflow 应用；
- 一个教学知识库；
- 对应应用和知识库 API Key。

## 4. Oracle Cloud 加分部署

不要发送 SSH 私钥或服务器密码。只需记录：

```dotenv
PUBLIC_HOST=
PUBLIC_DOMAIN=
API_DOMAIN=
DIFY_DOMAIN=
SSH_USER=
SERVER_ARCH=
SERVER_OS=
```

还需要服务器的 CPU 核心、内存、磁盘和 Docker 状态，用于判断是否能够同时部署 Dify。

## 5. 教师业务数据

收到后需要提供：

- 文件格式：CSV、Excel、SQL 或 JSON；
- 字段说明；
- 主键和关联字段；
- 是否脱敏；
- 是否允许上传到外部模型；
- 标准测试账号和预期结果。

## 6. 教师知识库文档

收到后需要提供：

- PDF/DOCX/TXT 文件；
- 文档用途和分类；
- 是否包含扫描版 PDF；
- 是否包含隐私或保密信息；
- 哪些角色能够检索；
- 是否提供标准测试问题和参考答案。

## 7. 后续最低配置反馈格式

后续只需回复：

```text
DeepSeek：已配置/未配置
DashScope：已配置/未配置
Dify：已启动，地址已写入 .env
Dify Chat 应用：已创建/未创建
Dify Workflow：已创建/未创建
Dify 知识库：已创建/未创建
教师数据：已收到/未收到
教师文档：已收到/未收到
Oracle 服务器：暂不部署/准备加分部署
```
