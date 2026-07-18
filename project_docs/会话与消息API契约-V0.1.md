# 会话与消息 API 契约（V0.1）

- OpenAPI 应用版本：`0.5.0`
- 统一前缀：`/api/v1`
- 认证方式：`Authorization: Bearer <access_token>`
- 关联决策：`DEC-20260717-014`

## 1. 通用规则

- 所有接口都使用当前 JWT 对应的数据库用户和租户，不接受客户端指定 `tenant_id` 或 `user_id`；
- 其他租户、同租户其他用户、已软删除或不存在的会话统一返回 HTTP 404 `conversation_not_found`；
- 日期时间使用带时区的 ISO 8601 字符串；
- 列表使用 `limit`、`offset` 和 `total`；
- 错误响应遵循《API 通用响应契约 V0.1》，并包含 `request_id`；
- 消息历史当前只允许查询。用户问题和 AI 完整回复由后续 AI Gateway 通过内部会话服务追加，不开放绕过 AI 流程的公共消息写入接口。

## 2. 数据结构

### 2.1 ConversationResponse

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "title": "商务咨询",
  "last_message_at": "2026-07-17T08:00:00Z",
  "created_at": "2026-07-17T07:50:00Z",
  "updated_at": "2026-07-17T08:00:00Z"
}
```

`last_message_at` 在尚无消息时为 `null`。响应不暴露内部 `tenant_id`、`user_id`、`deleted_at` 和 `next_message_position`。

### 2.2 MessageResponse

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "position": 1,
  "role": "user",
  "content": "请介绍平台能力",
  "metadata": {},
  "created_at": "2026-07-17T08:00:00Z"
}
```

约束：

- `position` 是会话内从 1 开始的单调正整数；
- `role` 可为 `user`、`assistant`、`system`、`tool`；
- 消息按 `position` 升序返回；
- 消息保存后不提供原地修改接口；
- `metadata` 只保存可公开的结构化业务元数据，禁止写入 API Key、JWT、密码或 Cookie。

## 3. 创建会话

### `POST /conversations`

请求：

```json
{
  "title": "  商务咨询  "
}
```

`title` 可省略或为去除空白后的空字符串，此时服务端使用“新对话”。最大长度为 200。

成功状态：HTTP 201，返回 `ConversationResponse`。

## 4. 查询当前用户会话

### `GET /conversations?limit=20&offset=0`

参数：

- `limit`：1 至 100，默认 20；
- `offset`：大于等于 0，默认 0。

成功响应：

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

只返回当前租户当前用户未软删除的会话。排序优先使用最后消息时间，其次使用更新时间和会话 ID，最近活动的会话在前。

## 5. 查询会话详情

### `GET /conversations/{conversation_id}`

成功状态：HTTP 200，返回 `ConversationResponse`。

目标不属于当前用户、已软删除或不存在时，返回：

```json
{
  "error": {
    "code": "conversation_not_found",
    "message": "会话不存在。"
  },
  "request_id": "请求追踪编号"
}
```

## 6. 查询消息历史

### `GET /conversations/{conversation_id}/messages?limit=100&offset=0`

参数：

- `limit`：1 至 200，默认 100；
- `offset`：大于等于 0，默认 0。

成功响应：

```json
{
  "items": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "position": 1,
      "role": "user",
      "content": "请介绍平台能力",
      "metadata": {},
      "created_at": "2026-07-17T08:00:00Z"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

仓储查询会直接连接会话表，并同时校验租户、用户和软删除状态。

## 7. 软删除会话

### `DELETE /conversations/{conversation_id}`

成功状态：HTTP 204，无响应体。

该操作设置会话的 `deleted_at`，不物理删除会话或历史消息。删除后：

- 会话不再出现在列表中；
- 会话详情和消息历史返回 404；
- 后续 AI Gateway 不得继续向该会话追加消息；
- 数据仍保留，用于未来审计、运行关联和按策略清理。

## 8. 主要错误码

| HTTP 状态 | 错误码 | 说明 |
|---|---|---|
| 401 | `not_authenticated` | 未提交有效 Bearer 访问令牌 |
| 401 | `invalid_token` | 访问令牌无效、过期或已吊销 |
| 403 | `user_disabled` | 当前数据库用户已禁用 |
| 404 | `conversation_not_found` | 会话不存在、已删除或不属于当前用户 |
| 422 | `validation_error` | UUID、分页参数或标题格式不合法 |
| 422 | `message_content_required` | 内部追加消息时正文为空 |
| 422 | `message_too_long` | 内部追加消息时正文超过 100000 字符 |

## 9. 后续 AI Gateway 接入约定

AI Gateway 阶段应遵守以下顺序：

1. 验证当前用户拥有且未删除目标会话；
2. 通过 `ConversationService.append_message` 保存用户问题；
3. 调用 DeepSeek 或阿里云百炼并输出统一 SSE 事件；
4. 流式完成后，把拼接后的完整助手回复作为一条 `assistant` 消息保存；
5. 在 `metadata` 中只保存提供商、模型、运行 ID 等非敏感信息；
6. 异常中断时记录 AI Run 状态，不保存伪造的完整助手回复。
