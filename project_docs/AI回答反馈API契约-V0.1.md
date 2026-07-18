# AI 回答反馈 API 契约（V0.1）

- 制定日期：2026-07-17
- 接口前缀：`/api/v1`
- 关联决策：`DEC-20260717-023`
- 权限：已登录用户，只能评价自己创建的 AI Run

## 1. 接口定位

```http
POST /api/v1/ai/runs/{run_id}/feedback
Authorization: Bearer <access-token>
Content-Type: application/json
```

用于对普通模型或 LangGraph Agent 已完成的最终回答提交赞踩和可选文字反馈。反馈同时关联 AI Run 和该 Run 的 `response_message_id`，但前端不提交 Message ID。

## 2. 请求

```json
{
  "rating": "negative",
  "comment": "回答没有说明退款期限。"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `rating` | `positive \| negative` | 是 | 稳定枚举 | 赞或踩 |
| `comment` | string/null | 否 | 去除首尾空白后最多 1000 字符 | 补充说明；空字符串保存为 null |

请求使用严格字段校验。`message_id`、`tenant_id`、`user_id`、模型参数及任何其他未声明字段均返回 HTTP 422，不能静默忽略。

## 3. 成功响应

首次提交和后续修改均返回 HTTP 200：

```json
{
  "id": "反馈 UUID",
  "run_id": "AI Run UUID",
  "message_id": "助手消息 UUID",
  "rating": "negative",
  "comment": "回答没有说明退款期限。",
  "created_at": "2026-07-17T12:00:00Z",
  "updated_at": "2026-07-17T12:00:00Z"
}
```

响应不包含 `tenant_id`、`user_id`、回答正文、模型 Key、供应商请求 ID 或数据库内部错误。反馈表同样不重复保存 `tenant_id` 和 `user_id`，所有权及后续租户统计通过关联 AI Run 推导。

## 4. 幂等与更新语义

每个 AI Run 只有一条当前反馈：

1. 第一次 POST 创建反馈；
2. 相同用户对同一 Run 再次 POST，原子更新 `rating`、`comment` 和 `updated_at`；
3. `id`、`run_id`、`message_id` 和 `created_at` 保持不变；
4. 并发重复提交由数据库唯一约束与 upsert 收敛为一条记录；
5. 校验与 upsert 在同一个数据库事务中完成：先锁定当前用户拥有的 Run，再校验回答 Message 与 Conversation，最后写入反馈；
6. 数据库通过 `(run_id, message_id) -> ai_runs(id, response_message_id)` 复合外键保证反馈始终指向该 Run 的最终回答；
7. 已存在反馈后不能原地替换该 Run 的 `response_message_id`；重新生成或修正回答应创建新的 AI Run，使反馈评价对象和统计口径保持稳定；
8. upsert 显式同步当前 `message_id`，使用 `RETURNING` 并刷新当前 ORM Session 中的已有实体，保证更新响应返回新评价而不是 Identity Map 中的旧值；
9. V0.1 不保留每次赞踩切换的历史事件。

## 5. 可评价条件

同时满足以下条件时才允许提交：

1. Run 属于当前访问令牌中的租户和用户；
2. Run 状态为 `succeeded`；
3. Run 已保存 `response_message_id`；
4. 回答消息关联由服务端读取，客户端不能覆盖；
5. Message ID 必须等于 Run 的 `response_message_id`，并且 Message 必须属于同一个 Conversation；
6. Message 的角色必须为 `assistant`；
7. Conversation 必须仍属于当前租户当前用户，且没有被软删除。

running、failed、cancelled、缺少回答消息、回答消息关联异常、消息角色异常或会话已软删除时，统一返回 HTTP 409 `ai_run_not_feedbackable`。

## 6. 权限与不存在语义

- 其他租户的 Run：HTTP 404 `ai_run_not_found`；
- 同租户其他用户的 Run：HTTP 404 `ai_run_not_found`；
- 不存在的 Run：HTTP 404 `ai_run_not_found`；
- 管理员也不能代替其他用户评价，以免污染满意度数据。

## 7. 错误响应

错误遵守 `API通用响应契约-V0.1.md`：

| HTTP | 错误码 | 条件 |
|---|---|---|
| 401 | 认证领域错误 | 未登录、令牌无效或过期 |
| 404 | `ai_run_not_found` | Run 不存在或不属于当前租户当前用户 |
| 409 | `ai_run_not_feedbackable` | Run 未成功完成或缺少回答消息 |
| 422 | `validation_error` | 枚举错误、评论超长、额外字段或路径 UUID 无效 |
| 503 | `ai_feedback_persistence_failed` | 反馈暂时无法持久化 |

错误响应、应用日志和决策日志不得包含反馈正文、回答正文、凭据、堆栈或数据库原始异常。

## 8. V0.1 非目标

- 管理员替用户评价；
- 对任意历史消息单独评价；
- 反馈修改历史和事件溯源；
- 举报、审核和批量导出；
- 知识查询未纳入 AI Run 前的独立反馈接口；
- 满意度统计接口，留给后续 analytics 阶段。
