# 语音合成 API 契约（V0.1）

- 制定日期：2026-07-17
- 接口前缀：`/api/v1`
- 关联决策：`DEC-20260717-025`
- 权限：任意已登录角色

## 1. 接口定位

```http
POST /api/v1/audio/tts
Authorization: Bearer <access-token>
Content-Type: application/json
```

接口把短文本转换为可直接播放的 MP3 或 WAV 音频。浏览器只调用 FastAPI，不直接访问 Dify，也不接触 Dify App Key、模型供应商凭据、内部应用 ID 或模型配置。

## 2. 请求

```json
{
  "text": "您好，您的退款申请已经进入审核流程。"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `text` | string | 是 | 去除首尾空白后 1～500 字符 | 需要合成的短文本 |

请求采用严格字段校验。`voice`、`language`、`model`、`provider`、`message_id`、`user`、任何 Key 以及其他未声明字段均返回 HTTP 422，不能静默忽略。

模型、声音和语言由 Dify 服务端统一配置，V0.1 固定使用 `qwen3-tts-flash`、`Cherry` 和 `zh-Hans`，前端不能覆盖。

## 3. 成功响应

```http
HTTP/1.1 200 OK
Content-Type: audio/mpeg 或 audio/wav
Cache-Control: no-store
Pragma: no-cache
X-Content-Type-Options: nosniff

<audio binary>
```

成功响应是二进制音频，不使用 JSON 包装。FastAPI 根据实际文件签名返回准确媒体类型：MP3 返回 `audio/mpeg`，RIFF/WAVE 返回 `audio/wav`。响应体必须非空且不得超过 5 MiB。服务端不把音频写入数据库或本地文件。

当前 Dify 通义插件存在“响应头声明 `audio/mpeg`，实际返回 RIFF/WAVE 字节”的行为，因此平台不得只依据上游 `Content-Type`。V0.1 不为统一格式额外引入转码依赖。

前端调用示例逻辑：

1. 使用登录后的 Bearer Token 发起 POST；
2. 把成功响应读取为 `Blob`；
3. 使用临时 Object URL 交给 `<audio>` 播放；
4. 播放结束或组件卸载时调用 `URL.revokeObjectURL`；
5. 不在 LocalStorage、IndexedDB 或日志中长期保存音频正文。

## 4. 用户标识与隐私

FastAPI 使用当前访问令牌中的租户 ID 和用户 ID 生成稳定的 SHA-256 用户别名，并把该别名作为 Dify `user` 字段。接口请求不能自行指定该字段。

成功响应和错误响应均不得包含：

- 平台租户 ID 或用户 ID；
- Dify App Key、Provider Key 或其他凭据；
- Dify App ID、Workflow ID 或模型凭据 ID；
- 上游原始错误正文、堆栈和请求对象；
- 音频生成供应商的内部请求标识。

## 5. 同步与存储语义

1. 每次请求同步生成一段音频；
2. V0.1 不提供幂等键，同一文本重复提交可能再次消耗模型额度；
3. FastAPI 不持久化音频正文，也不创建数据库记录；
4. 接口不保证跨请求返回完全相同的音频字节；
5. 文本超过 500 字符时由调用方缩短，V0.1 不自动分段拼接；
6. 响应使用 `no-store`，避免共享缓存保存用户生成内容。

## 6. 上游校验

FastAPI 对 Dify 响应执行以下校验：

1. HTTP 状态必须为成功状态；
2. 上游声明类型必须是音频类型，且响应体必须能识别为 MP3 或 RIFF/WAVE；
3. 响应体必须非空；
4. 累计响应不得超过 5 MiB；
5. FastAPI 根据文件签名修正对外 `Content-Type`，不直接复制可能错误的上游响应头；
6. HTTP Client 禁用系统代理继承，保证本地 Dify 地址不被代理转发；
7. 认证失败、限流、超时、网络异常、业务拒绝和协议异常分别转换为平台统一错误。

## 7. 错误响应

错误遵守 `API通用响应契约-V0.1.md`：

| HTTP | 错误码 | 条件 |
|---|---|---|
| 401 | 认证领域错误 | 未登录、令牌无效或过期 |
| 422 | `validation_error` | 文本为空、超过 500 字符、类型错误或包含额外字段 |
| 502 | `audio_upstream_authentication_failed` | Dify 拒绝服务端凭据 |
| 502 | `audio_upstream_unavailable` | Dify 网络不可达或返回 5xx |
| 502 | `audio_upstream_rejected` | Dify 拒绝本次合成请求 |
| 502 | `audio_upstream_protocol_error` | Dify 返回无法识别的音频、空音频、超限音频或无效成功响应 |
| 503 | `audio_service_not_configured` | Dify 地址或 Chat App Key 未配置 |
| 503 | `audio_upstream_rate_limited` | Dify 或模型供应商限流 |
| 504 | `audio_upstream_timeout` | Dify 调用超时 |

错误消息必须是平台定义的中文安全消息，不得透传 Dify 或模型供应商响应正文。

## 8. V0.1 非目标

- 前端选择模型、声音、语言、语速、音调或音量；
- 语音转文字 ASR；
- 批量、异步或超长文本合成；
- 音频缓存、历史记录、下载中心和对象存储；
- 针对音频内容的审计与敏感词二次处理；
- 按租户统计 TTS 调用量和费用，该能力留给后续 analytics 阶段。
