# API 通用响应契约（V0.1）

- 适用范围：东软智慧商务 AI 助手平台 FastAPI 接口
- API 前缀：`/api/v1`
- 制定日期：2026-07-17

## 1. 成功响应

成功响应保持各领域自己的 Pydantic 模型，不额外增加统一 `data` 包装层，避免 SSE、文件下载和普通 JSON 被强制使用同一种响应结构。

示例：

```json
{
  "status": "ok",
  "service": "东软智慧商务 AI 助手平台",
  "environment": "development"
}
```

## 2. 请求追踪

### 2.1 请求头

客户端可以发送：

```http
X-Request-ID: frontend-demo-001
```

请求 ID 只允许以下字符：

- 英文字母；
- 数字；
- `.`、`_`、`-`；
- 长度为 1 至 64 个字符。

如果客户端未提供请求 ID，或请求 ID 不符合规则，后端会生成新的 UUID。客户端不能把用户输入、Token、手机号或其他敏感数据作为请求 ID。

### 2.2 响应头

所有普通 HTTP 响应都返回：

```http
X-Request-ID: frontend-demo-001
```

前端显示错误提示时可以同时显示或记录该编号，用于关联服务端结构化日志。

## 3. 统一错误响应

```json
{
  "error": {
    "code": "validation_error",
    "message": "请求参数校验失败。",
    "details": [
      {
        "field": "body.username",
        "message": "Field required",
        "type": "missing"
      }
    ]
  },
  "request_id": "frontend-demo-001"
}
```

字段说明：

| 字段 | 类型 | 是否必有 | 说明 |
|---|---|---|---|
| `error.code` | string | 是 | 稳定机器错误码，前端不得依赖自然语言判断错误类型 |
| `error.message` | string | 是 | 可向用户显示的安全错误信息 |
| `error.details` | object / array | 否 | 字段校验或业务错误的公开细节 |
| `request_id` | string | 是 | 与响应头及服务端日志一致的请求追踪编号 |

## 4. 基础错误码

| HTTP 状态 | 错误码 | 用途 |
|---|---|---|
| 401 | `unauthorized` | 未登录或令牌无效 |
| 403 | `forbidden` | 已登录但权限不足 |
| 404 | `not_found` | 资源或接口不存在 |
| 405 | `method_not_allowed` | HTTP 方法不支持 |
| 409 | `conflict` | 唯一约束、状态或资源冲突 |
| 422 | `validation_error` | 请求参数未通过 Pydantic 校验 |
| 429 | `rate_limited` | 请求频率超过限制 |
| 500 | `internal_server_error` | 未预期的服务端错误 |

各领域可以增加稳定业务错误码，例如 `invalid_credentials`、`user_disabled`、`conversation_not_found`，但必须继续使用同一响应结构。

## 5. 安全约束

错误响应不得包含：

- Python Traceback；
- 数据库连接地址和 SQL 参数；
- API Key、JWT、Cookie 或密码；
- 第三方 SDK 的完整内部异常；
- 服务器绝对路径。

未知异常统一返回 `internal_server_error`，详细堆栈只写入服务端日志。

参数校验错误的 `details` 只返回字段位置、公开错误信息和错误类型，不回显完整请求输入值。

## 6. 结构化访问日志

每个普通 HTTP 请求至少记录以下字段：

```json
{
  "timestamp": "2026-07-17T00:00:00+00:00",
  "level": "INFO",
  "logger": "app.http",
  "message": "request_completed",
  "request_id": "frontend-demo-001",
  "method": "GET",
  "path": "/api/v1/health",
  "status_code": 200,
  "duration_ms": 2.5
}
```

访问日志不记录请求正文、Authorization、Cookie 和模型密钥。

## 7. SSE 流式接口约定

SSE 成功响应仍使用 `text/event-stream`，中间件不得读取、缓存或重新包装事件流正文。

- 响应开始前发生异常：可以返回普通统一 JSON 错误；
- 响应开始后发生异常：不能把已经开始的 SSE 改写为 JSON；服务端记录失败日志，未来由流内 `error` 事件传递安全错误信息；
- SSE 响应头仍返回 `X-Request-ID`。

具体流内事件类型将在 AI 流式对话阶段单独形成版本化契约。
