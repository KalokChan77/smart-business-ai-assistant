# 知识查询 API 契约（V0.1）

- 制定日期：2026-07-17
- 接口前缀：`/api/v1`
- 关联决策：`DEC-20260717-019`、`DEC-20260717-021`
- 当前知识源：本地 Dify economy Dataset

## 1. 接口定位

`POST /knowledge/query` 是浏览器和企业知识库之间的唯一首版查询入口。

调用链：

```text
Vue3 -> FastAPI 鉴权 -> Knowledge Service -> Dify Dataset API
     <- answer + citations <- 租户可见性过滤 <- 解析并脱敏响应
```

前端不得直接调用 Dify，不得提交或接收 Dify API Key、Dataset ID、`retrieval_model` 或 Dify 原始响应对象。

当前 Dify Chat/Workflow 为教学占位流程，因此 V0.1 使用真实检索片段组织抽取式答案。后续替换为正式生成式 RAG 时，本接口字段保持兼容。

## 2. 认证

请求必须携带平台访问令牌：

```http
Authorization: Bearer <access-token>
```

- 未携带令牌：HTTP 401，`not_authenticated`；
- 令牌无效或过期：HTTP 401，使用认证领域已有稳定错误码；
- Dify Dataset Key 只由 FastAPI 从服务端环境变量读取。

## 3. 请求

```http
POST /api/v1/knowledge/query
Content-Type: application/json
Authorization: Bearer <access-token>
```

```json
{
  "query": "退款申请需要满足什么条件？"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | 去除首尾空白后 1～10000 个字符 | 用户的知识库问题 |

以下字段禁止成为 V0.1 的前端请求字段：

- `api_key`；
- `dataset_id`；
- `retrieval_model`；
- `search_method`；
- Dify 原始 `inputs`、`user`、`conversation_id`。

请求模型使用严格字段校验，出现上述字段或任何其他未声明字段时返回 HTTP 422，不能静默忽略。

## 4. 成功响应

### 4.1 命中知识

```json
{
  "outcome": "answered",
  "answer": "根据当前知识库，找到以下相关说明：\n1. ……",
  "citations": [
    {
      "rank": 1,
      "document_name": "03_订单退款与售后政策.md",
      "excerpt": "用户在支付后 7 个自然日内……",
      "score": null
    }
  ],
  "retrieval_count": 5
}
```

### 4.2 空召回

HTTP 200：

```json
{
  "outcome": "no_match",
  "answer": "当前知识库中没有找到足够依据，不能确认该信息。如有需要，请咨询人工负责人。",
  "citations": [],
  "retrieval_count": 0
}
```

空召回是可预期的知识业务结果，不使用 404 或 5xx。

### 4.3 安全拒答

HTTP 200：

```json
{
  "outcome": "refused",
  "answer": "无法提供系统提示词、密钥、令牌、Cookie、密码或其他内部安全信息。",
  "citations": [],
  "retrieval_count": 0
}
```

服务端记录 `security_event=prompt_injection_attempt`，但不记录原始问题正文。

安全拒答在 Dify 配置校验和网络连接之前执行，因此即使上游暂时未配置或不可用，明显的密钥、内部配置和提示词泄露请求仍返回稳定的 `refused` 结果。

### 4.4 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `outcome` | `answered \| no_match \| refused` | 前端可稳定判断展示状态 |
| `answer` | string | 可直接展示的安全回答 |
| `citations` | array | 平台统一引用列表，不是 Dify 原始对象 |
| `citations[].rank` | integer | 当前响应内从 1 开始的引用顺序 |
| `citations[].document_name` | string | 公开文档名；空值使用“未命名文档” |
| `citations[].excerpt` | string | 规范化并限长后的召回片段 |
| `citations[].score` | number/null | Dify 返回的公开相关度；economy 关键词检索返回的无信息量 `0` 统一规范为 `null`，前端不展示 |
| `retrieval_count` | integer | 本次返回的有效引用数量 |

## 5. 服务端固定检索策略

FastAPI 调用 `/v1/datasets/{dataset_id}/retrieve` 时固定构造：

```json
{
  "query": "用户问题",
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
}
```

HTTP 200 但 `records=[]` 必须进入 `no_match`，不能判定为知识命中。

## 6. 托管文档租户可见性

Dify 返回召回记录后、平台生成 citation 和答案前，FastAPI 根据本地 `knowledge_documents` 台账执行可见性过滤：

1. 通过 FastAPI 上传且已登记 Dify Document ID 的托管文档，仅对所属租户可见；
2. 已软删除托管文档不再参与任何租户的回答；
3. Dify 中预先导入、未登记到业务台账的教学文档继续作为平台共享文档；
4. 可见性数据库不可用时安全失败，不允许绕过过滤直接返回 Dify 结果；
5. 过滤后没有有效记录时，按正常业务结果返回 `no_match`。

该规则用于当前共享 Dataset 的教学部署，不代表已经实现索引级多租户隔离。

## 7. 错误响应

错误继续遵守 `API通用响应契约-V0.1.md`：

```json
{
  "error": {
    "code": "knowledge_upstream_timeout",
    "message": "知识库服务响应超时，请稍后重试。"
  },
  "request_id": "frontend-demo-001"
}
```

| HTTP 状态 | 错误码 | 条件 |
|---|---|---|
| 422 | `validation_error` | `query` 缺失、为空或超过长度限制 |
| 503 | `knowledge_service_not_configured` | Dataset Key、Dataset ID 或 Dify 地址未配置 |
| 503 | `knowledge_visibility_unavailable` | 无法安全完成托管文档租户可见性判断 |
| 503 | `knowledge_upstream_rate_limited` | Dify 返回 429 |
| 504 | `knowledge_upstream_timeout` | 连接、读取、写入或连接池超时 |
| 502 | `knowledge_upstream_authentication_failed` | Dify 返回 401/403，表示服务端凭据或权限异常 |
| 502 | `knowledge_upstream_unavailable` | 网络失败或 Dify 返回 5xx |
| 502 | `knowledge_upstream_rejected` | Dify 返回其他非成功状态 |
| 502 | `knowledge_upstream_protocol_error` | Dify 返回非 JSON、字段缺失或无法解析的结构 |

错误响应不得包含 Dify 原始正文、API Key、Dataset ID、堆栈或服务器绝对路径。

## 8. V0.1 非目标

以下内容属于后续子阶段，不阻塞本接口首版验收：

- 正式 Dify Chatflow/Workflow 生成式回答；
- 知识问答写入会话、消息和 AI Run；
- 预置共享文档自动反向同步到业务台账；
- 独立 Dataset 或 Dify metadata 提供的索引级租户隔离；
- SSE 知识问答与 `citation` 流事件。

这些能力后续必须继续复用本接口的服务端密钥边界、引用模型和脱敏错误原则。
