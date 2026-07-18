# AI 流式对话 API 契约（V0.1）

- OpenAPI 应用版本：`0.7.0`
- 统一前缀：`/api/v1`
- 认证方式：`Authorization: Bearer <access_token>`
- 关联决策：`DEC-20260717-015`、`DEC-20260717-016`

## 1. 普通模型流式对话

### `POST /ai/chat/stream`

请求头：

```http
Authorization: Bearer <access_token>
X-Request-ID: ai-chat-request-001
Content-Type: application/json
```

`X-Request-ID` 可由客户端提供，格式为 1 至 64 位字母、数字、点、下划线或连字符；未提供或格式不合法时由服务端生成。同一租户、同一用户重复使用相同请求 ID 会返回 HTTP 409，避免浏览器重试重复保存用户消息。

请求体：

```json
{
  "conversation_id": "00000000-0000-0000-0000-000000000000",
  "message": "请介绍平台能力",
  "provider": "deepseek"
}
```

字段规则：

- `conversation_id`：必须属于当前租户当前用户，且会话未软删除；
- `message`：去除首尾空白后不能为空，最大 100000 字符；
- `provider`：可选，支持 `deepseek`、`dashscope`；省略时使用服务端 `LLM_PROVIDER`；
- 客户端不能直接指定模型名，模型由服务端环境变量控制。

成功响应头：

```http
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-store
X-Accel-Buffering: no
X-Request-ID: ai-chat-request-001
```

## 2. LangGraph 工具调用 Agent

### `POST /ai/agent/stream`

请求头与普通模型接口相同，使用独立请求 ID：

```http
Authorization: Bearer <access_token>
X-Request-ID: ai-agent-request-001
Content-Type: application/json
```

请求体：

```json
{
  "conversation_id": "00000000-0000-0000-0000-000000000000",
  "message": "请计算 12 * 8 + 4",
  "provider": "deepseek"
}
```

字段规则与 `/ai/chat/stream` 一致。Agent 会根据问题决定是否调用已注册工具，客户端不能指定任意工具名或直接提交工具执行参数。

第一阶段注册工具：

| 工具名 | 用途 | 安全边界 |
|---|---|---|
| `calculate_business_metric` | 计算数字、括号和基本运算符组成的算术表达式 | 使用 AST 白名单；禁止函数调用、属性访问、动态代码和超限结果 |
| `lookup_demo_business_policy` | 查询模拟退款、账户安全或产品套餐政策 | 只读取代码内置教学模拟数据，无文件、数据库和网络写操作 |

Agent 执行约定：

- 图结构为 `START -> model -> tools 或 END`，工具完成后返回模型生成最终回答；
- 使用递归上限防止模型反复调用工具；
- `AI Run.mode` 固定为 `agent`；
- 只把用户消息和最终助手消息写入长期会话，中间模型消息与 ToolMessage 不落库；
- 助手消息元数据记录实际工具名称与调用次数；
- 事件解析使用 LangGraph 稳定的 v2 事件协议，不依赖实验性 v3 结构。

## 3. SSE 事件协议

事件顺序状态机：

```text
普通聊天：metadata -> token* -> message_end | error
Agent：metadata -> (token | tool_start | tool_end)* -> message_end | error
```

- `metadata` 只出现一次且必须是首个事件；
- `token` 可出现零次或多次；
- Agent 的 `token` 与工具事件可能交错，前端不能假设所有 Token 都在工具调用之后；
- 每个 `tool_end` 对应一个已经出现的 `tool_start`，一次 Run 可以调用多个工具；
- `message_end` 与 `error` 是互斥终止事件，各自最多出现一次；
- 收到终止事件后服务端关闭事件流。

### 3.1 metadata

```text
event: metadata
data: {"request_id":"ai-chat-request-001","run_id":"...","conversation_id":"...","provider":"deepseek","model":"deepseek-chat","mode":"chat","user_message_id":"...","user_message_position":1}
```

发送该事件前，AI Run 和用户消息已经保存成功。

Agent 的 `metadata` 还包含可用工具列表：

```text
event: metadata
data: {"request_id":"ai-agent-request-001","run_id":"...","conversation_id":"...","provider":"deepseek","model":"deepseek-chat","mode":"agent","tools":["calculate_business_metric","lookup_demo_business_policy"],"user_message_id":"...","user_message_position":1}
```

### 3.2 token

```text
event: token
data: {"run_id":"...","delta":"平台"}
```

`delta` 只是本次新增文本。前端按接收顺序拼接，不应把每个 Token 当成独立历史消息。Agent 运行时可在工具事件前后产生 Token，最终以持久化后的助手消息为完整结果。

### 3.3 tool_start

```text
event: tool_start
data: {"run_id":"...","tool":"calculate_business_metric","input":{"expression":"12 * 8 + 4"}}
```

仅 Agent 接口发送。`input` 会经过长度限制和安全序列化，不包含凭据、内部对象或异常堆栈。前端可用该事件显示“正在调用工具”。

### 3.4 tool_end

```text
event: tool_end
data: {"run_id":"...","tool":"calculate_business_metric","output":"{\"expression\":\"12 * 8 + 4\",\"result\":100}"}
```

仅 Agent 接口发送。工具输出会限制长度；该事件表示工具节点已结束，但不代表整个 Agent Run 已完成。

### 3.5 message_end

```text
event: message_end
data: {"request_id":"ai-chat-request-001","run_id":"...","message_id":"...","message_position":2,"input_tokens":10,"output_tokens":8}
```

收到该事件表示：

- 模型正常完成；
- 完整助手回复已经作为一条 `assistant` 消息保存；
- AI Run 已标记为 `succeeded`；
- Token 用量在厂商返回时写入，不可用时可以为 `null`。

Agent 的 `message_end` 额外包含 `tool_call_count`：

```text
event: message_end
data: {"request_id":"ai-agent-request-001","run_id":"...","message_id":"...","message_position":2,"tool_call_count":1,"input_tokens":20,"output_tokens":12}
```

### 3.6 error

```text
event: error
data: {"request_id":"ai-chat-request-001","run_id":"...","code":"ai_provider_unavailable","message":"模型服务暂时不可用。"}
```

收到该事件表示流已经失败并结束。AI Run 标记为 `failed`，已保存的用户消息保留，不保存不完整的助手消息。响应不包含厂商原始响应体、API Key、JWT、Cookie 或内部异常堆栈。

## 4. 流开始前与流开始后的错误边界

流开始前发生的认证、参数、配置、会话所有权或请求 ID 冲突，使用普通 JSON 错误响应和对应 HTTP 状态：

| HTTP 状态 | 错误码 | 说明 |
|---|---|---|
| 401 | `not_authenticated` / `invalid_token` | 未认证或令牌无效 |
| 404 | `conversation_not_found` | 会话不存在、已删除或不属于当前用户 |
| 409 | `ai_request_conflict` | 相同所有者和请求 ID 的 Run 已存在 |
| 422 | `validation_error` | 请求体或字段格式错误 |
| 503 | `ai_provider_not_configured` | 所选 Provider 的密钥、地址或模型未配置 |

SSE 响应开始后不能改写成 JSON 500，因此模型调用和后续持久化错误通过 `error` 事件表达：

| 错误码 | 说明 |
|---|---|
| `ai_provider_authentication_failed` | 模型服务拒绝认证 |
| `ai_provider_rate_limited` | 模型服务限流 |
| `ai_provider_timeout` | 模型响应超时 |
| `ai_provider_unavailable` | 模型服务网络或服务异常 |
| `ai_provider_protocol_error` | 厂商流式数据无法解析 |
| `ai_empty_response` | 模型未返回有效助手内容 |
| `ai_stream_failed` | 未分类的安全兜底错误 |
| `agent_empty_response` | Agent 未产生有效最终回答 |
| `agent_recursion_limit` | Agent 工具循环达到递归上限 |
| `agent_execution_failed` | Agent 模型或图执行出现未分类失败 |

客户端断开连接时，服务端取消上游流并将 Run 标记为 `cancelled`，不发送后续终止事件，也不保存不完整助手消息。

## 5. 查询 AI Run

### `GET /ai/runs/{run_id}`

只允许创建该 Run 的同一租户同一用户查询。其他用户或不存在的 Run 返回 HTTP 404 `ai_run_not_found`。

成功响应：

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "conversation_id": "00000000-0000-0000-0000-000000000000",
  "request_id": "ai-chat-request-001",
  "provider": "dashscope",
  "model": "qwen-plus",
  "mode": "agent",
  "status": "succeeded",
  "prompt_message_id": "00000000-0000-0000-0000-000000000000",
  "response_message_id": "00000000-0000-0000-0000-000000000000",
  "input_tokens": 10,
  "output_tokens": 2,
  "error_code": null,
  "started_at": "2026-07-17T09:00:00Z",
  "completed_at": "2026-07-17T09:00:02Z",
  "created_at": "2026-07-17T09:00:00Z",
  "updated_at": "2026-07-17T09:00:02Z"
}
```

状态值：

- `running`：用户消息已保存，模型正在生成；
- `succeeded`：完整助手消息已保存；
- `failed`：模型或持久化失败，没有完整助手消息；
- `cancelled`：客户端断开或任务被取消。

模式值：

- `chat`：普通模型流式对话；
- `agent`：LangGraph 工具调用 Agent。

## 6. 持久化与安全约定

- 用户消息在流开始前保存，元数据记录 `ai_run_id`；
- 助手回复只在正常结束后一次性保存，元数据记录 Run、Provider 和模型；
- Agent 中间模型消息和工具消息不写入长期会话，最终助手消息记录工具名称和调用次数；
- 不逐 Token 写数据库；
- `AI Run` 使用 `(tenant_id, user_id, request_id)` 唯一约束；
- Run 查询始终校验租户和用户，不只按 UUID 查询；
- 数据库只保存安全错误码和通用错误信息，不保存厂商原始错误体；
- 所有模型凭据只通过环境变量加载，不出现在 API、日志、文档和前端代码中。
