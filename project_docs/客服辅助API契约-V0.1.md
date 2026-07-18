# 客服辅助 API 契约（V0.1）

- 制定日期：2026-07-17
- 接口前缀：`/api/v1/customer-service`
- 关联决策：`DEC-20260717-024`
- 核心原则：AI 只生成建议，最终回复必须由客服或管理员人工确认

## 1. 角色与可见性

| 能力 | user / decision_maker | customer_service / admin |
|---|---|---|
| 创建自己的工单 | 允许 | 允许 |
| 查询工单列表 | 仅自己的工单 | 当前租户全部工单 |
| 查询工单详情 | 仅自己的工单 | 当前租户全部工单 |
| 问题分类 | 禁止，HTTP 403 | 允许 |
| 生成建议回复 | 禁止，HTTP 403 | 允许 |
| 编辑并确认回复 | 禁止，HTTP 403 | 允许 |

其他租户资源、普通用户访问他人工单和不存在资源统一返回 HTTP 404，避免泄露资源是否存在。

详情响应按角色分为两类：

- `public`：请求者公开视图，只包含工单业务字段和人工确认后的最终回复；
- `internal`：客服内部视图，可以包含请求者、处理人、AI 草稿、引用、质检和工作流信息。

普通请求者在人工确认前看不到任何草稿内容；公开响应始终不返回 `tenant_id`、员工 UUID、质检说明、工作流版本或 AI 内部建议。

## 2. 稳定枚举

### 2.1 工单状态

- `open`：新建待处理；
- `in_progress`：已分类或正在处理；
- `resolved`：客服已经确认最终回复；
- `closed`：预留状态，V0.1 不提供关闭接口。

### 2.2 问题分类

- `refund_after_sales`：退款、退货、售后；
- `account_security`：账号、登录、验证码、隐私和安全；
- `product_service`：产品、套餐、价格和服务；
- `knowledge_document`：知识库、文档、上传和检索；
- `technical_support`：系统故障、报错和使用异常；
- `other`：未命中稳定类别。

### 2.3 优先级

`low | normal | high | urgent`

### 2.4 建议与质检状态

- 建议状态：`draft | confirmed`；
- 质检状态：`passed | needs_review`。

## 3. 创建工单

```http
POST /api/v1/customer-service/tickets
Authorization: Bearer <access-token>
Content-Type: application/json
```

请求：

```json
{
  "subject": "退款到账时间咨询",
  "description": "订单已经提交退款申请，通常需要多久处理完成？"
}
```

约束：

- `subject`：去除首尾空白后 1 至 200 字符；
- `description`：去除首尾空白后 1 至 10000 字符；
- 严格拒绝 `tenant_id`、`requester_user_id`、`status`、`category`、`assigned_user_id` 等服务端字段。

成功返回 HTTP 201，初始状态为 `open`、优先级为 `normal`，分类字段为空。返回公开工单结构，例如：

```json
{
  "id": "工单 UUID",
  "subject": "退款到账时间咨询",
  "description": "订单已经提交退款申请，通常需要多久处理完成？",
  "status": "open",
  "category": null,
  "priority": "normal",
  "resolved_at": null,
  "created_at": "2026-07-17T12:00:00Z",
  "updated_at": "2026-07-17T12:00:00Z"
}
```

## 4. 查询工单列表

```http
GET /api/v1/customer-service/tickets?status=open&category=refund_after_sales&limit=20&offset=0
```

- `status` 和 `category` 可选；
- `limit` 为 1 至 100，`offset` 不小于 0；
- 按 `created_at DESC, id DESC` 稳定排序；
- 普通用户只返回自己的工单，客服和管理员返回当前租户工单。
- 列表项统一使用公开工单结构，不返回 `tenant_id`、请求者 UUID、处理人 UUID 或分类推理说明；客服需要处理上下文时再查询内部详情。

响应：

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

## 5. 查询工单详情

```http
GET /api/v1/customer-service/tickets/{ticket_id}
```

普通请求者成功返回公开视图。人工确认前：

```json
{
  "view": "public",
  "ticket": {
    "id": "工单 UUID",
    "subject": "退款到账时间咨询",
    "description": "订单已经提交退款申请，通常需要多久处理完成？",
    "status": "in_progress",
    "category": "refund_after_sales",
    "priority": "high",
    "resolved_at": null,
    "created_at": "2026-07-17T12:00:00Z",
    "updated_at": "2026-07-17T12:01:00Z"
  },
  "confirmed_reply": null
}
```

人工确认后，`confirmed_reply` 只返回正式回复和确认时间：

```json
{
  "view": "public",
  "ticket": {
    "id": "工单 UUID",
    "subject": "退款到账时间咨询",
    "description": "订单已经提交退款申请，通常需要多久处理完成？",
    "status": "resolved",
    "category": "refund_after_sales",
    "priority": "high",
    "resolved_at": "2026-07-17T12:05:00Z",
    "created_at": "2026-07-17T12:00:00Z",
    "updated_at": "2026-07-17T12:05:00Z"
  },
  "confirmed_reply": {
    "final_reply": "您好，退款审核结果将按原支付渠道处理……",
    "confirmed_at": "2026-07-17T12:05:00Z"
  }
}
```

客服或管理员返回 `view=internal`，内部 `ticket` 可以包含 `requester_user_id`、`assigned_user_id`、分类置信度和分类理由，并通过 `reply_suggestion` 返回当前草稿或已确认建议。

响应不得包含 Dify Dataset ID、Dify Document ID、API Key、提示词、第三方原始响应或数据库异常。

## 6. 问题分类

```http
POST /api/v1/customer-service/classify
Authorization: Bearer <customer-service-or-admin-token>
Content-Type: application/json
```

请求：

```json
{
  "ticket_id": "工单 UUID"
}
```

成功返回 HTTP 200：

```json
{
  "ticket_id": "工单 UUID",
  "category": "refund_after_sales",
  "priority": "high",
  "confidence": 90,
  "reason": "命中退款与到账相关关键词。",
  "status": "in_progress",
  "assigned_user_id": "当前客服 UUID"
}
```

分类结果保存到工单。已解决或已关闭工单返回 HTTP 409 `customer_ticket_not_actionable`。

## 7. 生成建议回复

```http
POST /api/v1/customer-service/reply-suggestions
Authorization: Bearer <customer-service-or-admin-token>
Content-Type: application/json
```

请求：

```json
{
  "ticket_id": "工单 UUID"
}
```

LangGraph V0.1 固定执行：

```text
classify -> retrieve_knowledge -> compose_reply -> quality_check
```

成功返回 HTTP 200。首次调用创建当前建议，确认前重复调用更新同一建议 ID；确认后再次生成返回 HTTP 409。

```json
{
  "id": "建议 UUID",
  "ticket_id": "工单 UUID",
  "status": "draft",
  "category": "refund_after_sales",
  "suggested_reply": "您好，关于您咨询的退款处理时间……",
  "final_reply": null,
  "knowledge_outcome": "answered",
  "citations": [
    {
      "rank": 1,
      "document_name": "订单退款与售后政策",
      "excerpt": "……",
      "score": 0.9
    }
  ],
  "quality_status": "passed",
  "quality_notes": [],
  "workflow_version": "customer-service-v1",
  "generated_by_user_id": "客服 UUID",
  "confirmed_by_user_id": null,
  "confirmed_at": null,
  "created_at": "2026-07-17T12:00:00Z",
  "updated_at": "2026-07-17T12:00:00Z"
}
```

空召回或安全拒答仍可生成安全的待核实建议，但必须返回 `quality_status=needs_review`，不得编造确定结论。

## 8. 人工编辑与确认

```http
POST /api/v1/customer-service/reply-suggestions/{suggestion_id}/confirm
Authorization: Bearer <customer-service-or-admin-token>
Content-Type: application/json
```

请求可以省略 `final_reply`，表示采用建议原文；也可以提交人工编辑内容：

```json
{
  "final_reply": "您好，退款审核通常需要……如超过时限请提供订单号，我们会继续核实。"
}
```

约束：人工编辑内容去除首尾空白后 1 至 5000 字符。

确认成功后：

1. 建议状态变为 `confirmed`；
2. 保存 `final_reply`、确认人和确认时间；
3. 工单状态变为 `resolved`；
4. 相同内容重复确认幂等返回当前结果；
5. 已确认后提交不同内容返回 HTTP 409 `reply_suggestion_already_confirmed`。

V0.1 只记录平台内确认，不调用外部短信、邮件、微信或客服发送接口。

## 9. 数据库与并发不变量

1. `users` 提供 `(id, tenant_id)` 复合唯一键；
2. 工单请求者和处理人必须通过 `(user_id, tenant_id)` 复合外键指向同租户用户；
3. 建议保存 `tenant_id`，并通过 `(ticket_id, tenant_id)` 复合外键绑定同租户工单；
4. 建议生成者和确认者必须通过复合外键指向同租户用户；
5. 关联了客服工单或审计记录的用户禁止物理删除，使用用户禁用状态代替，数据库删除策略为 `RESTRICT`；
6. `confirmed` 建议必须同时具有非空 `final_reply`、`confirmed_by_user_id` 和 `confirmed_at`；
7. 重新生成与确认都统一按 `CustomerTicket -> ReplySuggestion` 获取行锁，避免相反锁顺序造成死锁；并发结果只能收敛为已确认状态，或返回明确的 HTTP 409。

## 10. 错误响应

错误遵守 `API通用响应契约-V0.1.md`：

| HTTP | 错误码 | 条件 |
|---|---|---|
| 401 | 认证领域错误 | 未登录、令牌无效或过期 |
| 403 | `forbidden` | 普通用户调用分类、生成或确认接口 |
| 404 | `customer_ticket_not_found` | 工单不存在、跨租户或当前普通用户无权查看 |
| 404 | `reply_suggestion_not_found` | 建议不存在或跨租户 |
| 409 | `customer_ticket_not_actionable` | 工单已经解决或关闭 |
| 409 | `reply_suggestion_already_confirmed` | 已确认后尝试重新生成或修改内容 |
| 422 | `validation_error` | 字段为空、过长、枚举错误、额外字段或 UUID 无效 |
| 502/503 | 知识库领域错误 | Dify 不可用、协议错误或租户可见性校验失败 |
| 503 | `customer_service_persistence_failed` | 客服业务状态暂时无法持久化 |

错误响应和日志不得包含工单正文、建议正文、最终回复、凭据、提示词、第三方响应正文或数据库原始异常。

## 11. V0.1 非目标

- 自动向外部渠道发送；
- 多轮工单消息时间线；
- 工单转派、关闭、重开和 SLA 升级；
- 保存每一次建议重新生成历史；
- 使用大模型直接决定最终分类或自动质检放行；
- 客服绩效、满意度和人工接管率统计，留给 analytics 阶段。
