# Dify 三个 API Key 配置指南

## 0. 前置条件

三个 Key 都由 Dify 自己生成，不是从 DeepSeek 或阿里云控制台获取。必须先完成：

1. Dify 本地部署并能登录；
2. 配置至少一个可用的大模型；
3. 创建 Chatflow 应用；
4. 创建 Workflow 应用；
5. 创建知识库并上传测试文档。

标准自托管访问地址通常为：

```text
管理界面：http://localhost
初始化界面：http://localhost/install
Service API：http://localhost/v1
```

如果 Docker Compose 修改了 Nginx 映射端口，例如映射为 8080，则 API 地址相应改为：

```text
http://localhost:8080/v1
```

## 1. DIFY_CHAT_APP_API_KEY

### 创建 Chatflow

1. 登录 Dify；
2. 进入“工作室 / Studio”；
3. 选择“从空白创建”；
4. 应用类型选择“Chatflow / 对话流”；
5. 应用名称建议：`智慧商务知识客服`；
6. 添加模型和知识检索节点；
7. 在预览窗口测试问题；
8. 发布应用。

### 生成 Key

1. 打开刚创建的 Chatflow；
2. 点击“访问 API / API Access”；
3. 点击“创建密钥 / Create Secret Key”；
4. 复制生成的应用 API Key；
5. 写入项目本地 `.env`：

```dotenv
DIFY_CHAT_APP_API_KEY=在本地填写
```

此 Key 对应的主要接口：

```text
POST /v1/chat-messages
```

每个 Chatflow 应用使用自己的应用 Key，不能用 Workflow Key 替代。

## 2. DIFY_WORKFLOW_API_KEY

### 创建 Workflow

1. 进入“工作室 / Studio”；
2. 选择“从空白创建”；
3. 应用类型选择“Workflow / 工作流”；
4. 应用名称建议：`智慧商务分析报告工作流`；
5. 在 Start 节点添加文本输入变量，例如 `query`；
6. 连接 LLM 节点；
7. 连接 End 节点，并输出 `result`；
8. 测试运行成功；
9. 发布工作流。

### 生成 Key

1. 打开 Workflow 应用；
2. 点击“访问 API / API Access”；
3. 创建应用 API Key；
4. 写入本地 `.env`：

```dotenv
DIFY_WORKFLOW_API_KEY=在本地填写
```

此 Key 对应的主要接口：

```text
POST /v1/workflows/run
```

未发布的 Workflow 不能通过 Service API 执行。

## 3. DIFY_DATASET_API_KEY

### 创建知识库

1. 进入“知识库 / Knowledge”；
2. 创建知识库；
3. 名称建议：`智慧商务教学模拟知识库`；
4. 上传 `project_docs/mock_knowledge/` 中的测试文档；
5. 完成分段和索引；
6. 使用“召回测试”确认问题可以检索到文档。

### 开启 API 并创建 Key

根据 Dify 版本，入口可能显示为“API Access”“知识库 API”或“服务 API”：

1. 在知识库或知识库 API 管理页面开启 API Access；
2. 创建 Knowledge API Key；
3. 写入本地 `.env`：

```dotenv
DIFY_DATASET_API_KEY=在本地填写
```

### 获取 Dataset ID

知识库 API 除 Key 外还必须提供知识库 ID。可在以下位置获得：

- 知识库 API 示例 URL；
- 浏览器知识库页面 URL；
- 调用 `GET /v1/datasets` 后读取返回对象的 `id`。

写入：

```dotenv
DIFY_DATASET_ID=知识库UUID
```

知识库主要接口：

```text
GET  /v1/datasets
POST /v1/datasets/{dataset_id}/document/create-by-file
POST /v1/datasets/{dataset_id}/retrieve
```

## 4. 完整环境变量

```dotenv
DIFY_BASE_URL=http://localhost/v1
DIFY_CHAT_APP_API_KEY=
DIFY_WORKFLOW_API_KEY=
DIFY_DATASET_API_KEY=
DIFY_DATASET_ID=
```

如果 FastAPI 本身在 Docker 容器中运行，而 Dify 通过 Mac 主机的端口提供服务，可以将地址调整为：

```dotenv
DIFY_BASE_URL=http://host.docker.internal/v1
```

## 5. Chat Key 测试

```bash
curl -X POST "$DIFY_BASE_URL/chat-messages" \
  -H "Authorization: Bearer $DIFY_CHAT_APP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {},
    "query": "人工客服几点上班？",
    "response_mode": "blocking",
    "conversation_id": "",
    "user": "team01-test"
  }'
```

## 6. Workflow Key 测试

输入字段必须与 Start 节点中的变量名一致。假设变量名为 `query`：

```bash
curl -X POST "$DIFY_BASE_URL/workflows/run" \
  -H "Authorization: Bearer $DIFY_WORKFLOW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {"query": "生成本周客服问题摘要"},
    "response_mode": "blocking",
    "user": "team01-test"
  }'
```

## 7. Dataset Key 测试

列出可访问知识库：

```bash
curl "$DIFY_BASE_URL/datasets?page=1&limit=20" \
  -H "Authorization: Bearer $DIFY_DATASET_API_KEY"
```

检索测试：

```bash
curl -X POST "$DIFY_BASE_URL/datasets/$DIFY_DATASET_ID/retrieve" \
  -H "Authorization: Bearer $DIFY_DATASET_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "退款申请需要满足什么条件？",
    "retrieval_model": {
      "search_method": "keyword_search",
      "reranking_enable": false,
      "reranking_model": {
        "reranking_provider_name": "",
        "reranking_model_name": ""
      },
      "top_k": 5,
      "score_threshold_enabled": false,
      "score_threshold": null
    }
  }'
```

当前教学知识库采用 `economy` 索引，因此检索请求显式使用 `keyword_search`。如果省略 `retrieval_model`，Dify 1.15.0 的 Service API 可能退回语义检索默认值，而 economy 知识库没有对应向量索引，最终会出现 HTTP 200 但 `records` 为空的情况。

## 8. 安全要求

- Key 只写入本地 `.env`；
- 不把 Key 粘贴到聊天、截图、README 或前端代码；
- `.env` 已被 `.gitignore` 排除；
- Vue3 不直接调用 Dify Service API；
- FastAPI 服务端负责携带 Key；
- 一个 Key 泄漏时只轮换对应应用或知识库 Key。

## 9. 本地 Dify Python 镜像重建

本项目为 Dify 1.15.0 的 economy 关键词检索补充了本地 Jieba 扩展镜像。需要重建 API、Worker、Beat 和 WebSocket 时，在 Dify Docker 目录执行：

```bash
./rebuild-local-api.sh
```

脚本会自动完成 Compose 配置检查、镜像构建、Python 服务重建、Nginx 上游刷新、API 健康检查和 Jieba 导入检查。脚本不读取或输出 Dify API Key。
