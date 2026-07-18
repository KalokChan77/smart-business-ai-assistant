# 分析统计 API 契约（V0.1）

- 制定日期：2026-07-17
- 接口前缀：`/api/v1`
- 关联决策：`DEC-20260717-026`
- 权限：当前租户 `admin` 或 `decision_maker`
- 时区：UTC

## 1. 公共时间参数

五个接口均支持：

```http
?start_date=2026-07-01&end_date=2026-07-17
```

| 参数 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `start_date` | ISO date | 否 | UTC 开始自然日，包含当天 |
| `end_date` | ISO date | 否 | UTC 结束自然日，包含当天 |

规则：

1. 两者均省略时，默认最近 30 个 UTC 自然日；
2. 只传 `end_date` 时，从该日向前取 30 天；
3. 只传 `start_date` 时，结束日期默认为当前 UTC 日期；
4. `start_date` 不能晚于 `end_date`；
5. 首尾日期包含在内，范围最多 366 天；
6. 未声明的额外查询参数返回 HTTP 422；
7. 所有响应均包含实际使用的 `period`：

```json
{
  "start_date": "2026-07-01",
  "end_date": "2026-07-17",
  "timezone": "UTC"
}
```

## 2. 总览指标

```http
GET /api/v1/analytics/overview
Authorization: Bearer <access-token>
```

成功响应：

```json
{
  "period": {
    "start_date": "2026-07-01",
    "end_date": "2026-07-17",
    "timezone": "UTC"
  },
  "consultation_count": 20,
  "resolved_consultation_count": 12,
  "resolution_rate": 60.0,
  "human_takeover_count": 15,
  "human_takeover_rate": 75.0,
  "ai_run_count": 30,
  "ai_terminal_run_count": 28,
  "ai_success_rate": 89.29,
  "feedback_count": 10,
  "positive_feedback_count": 8,
  "satisfaction_rate": 80.0,
  "top_questions": [
    {
      "question": "退款多久到账？",
      "count": 4
    }
  ],
  "summary_cards": [
    {
      "code": "consultation_volume",
      "title": "咨询量",
      "value": "20",
      "description": "所选时间范围内共创建 20 条客服咨询。"
    }
  ]
}
```

口径：

- 咨询量：范围内创建的客服工单；
- 已解决：这些工单当前状态为 `resolved|closed`；
- 人工接管：这些工单的 `assigned_user_id` 非空；
- AI 成功率：成功终态 Run / 全部终态 Run，`running` 不进入分母；
- 满意度：范围内正面反馈 / 全部反馈；
- 高频问题：相同工单主题至少出现 2 次，最多 5 条，只返回主题和数量；
- 摘要卡片由确定性规则生成，不调用大模型。

## 3. 咨询量趋势

```http
GET /api/v1/analytics/consultations
Authorization: Bearer <access-token>
```

```json
{
  "period": {
    "start_date": "2026-07-15",
    "end_date": "2026-07-17",
    "timezone": "UTC"
  },
  "points": [
    {
      "date": "2026-07-15",
      "consultation_count": 0,
      "resolved_count": 0,
      "human_takeover_count": 0
    },
    {
      "date": "2026-07-16",
      "consultation_count": 3,
      "resolved_count": 2,
      "human_takeover_count": 2
    },
    {
      "date": "2026-07-17",
      "consultation_count": 5,
      "resolved_count": 1,
      "human_takeover_count": 4
    }
  ]
}
```

必须返回范围内每一个 UTC 日期；没有咨询的日期补 0。`resolved_count` 与 `human_takeover_count` 是按创建日期形成的工单队列当前状态统计，不表示解决动作发生日期。

## 4. 问题分类分布

```http
GET /api/v1/analytics/categories
Authorization: Bearer <access-token>
```

```json
{
  "period": {
    "start_date": "2026-07-01",
    "end_date": "2026-07-17",
    "timezone": "UTC"
  },
  "total": 20,
  "items": [
    {
      "category": "refund_after_sales",
      "count": 8,
      "percentage": 40.0
    },
    {
      "category": "unclassified",
      "count": 2,
      "percentage": 10.0
    }
  ]
}
```

`category` 固定为：

- `refund_after_sales`
- `account_security`
- `product_service`
- `knowledge_document`
- `technical_support`
- `other`
- `unclassified`

响应始终返回全部七类，数量为 0 的分类也保留，顺序固定，方便前端图表稳定渲染。

## 5. 满意度统计

```http
GET /api/v1/analytics/satisfaction
Authorization: Bearer <access-token>
```

```json
{
  "period": {
    "start_date": "2026-07-01",
    "end_date": "2026-07-17",
    "timezone": "UTC"
  },
  "feedback_count": 10,
  "positive_count": 8,
  "negative_count": 2,
  "satisfaction_rate": 80.0
}
```

反馈租户通过关联 AI Run 推导，不能只查询反馈表。时间范围使用反馈的 `created_at`。没有反馈时所有数量和满意度均返回 0。

## 6. AI Run 统计

```http
GET /api/v1/analytics/ai-runs
Authorization: Bearer <access-token>
```

```json
{
  "period": {
    "start_date": "2026-07-01",
    "end_date": "2026-07-17",
    "timezone": "UTC"
  },
  "total": 30,
  "running": 2,
  "succeeded": 25,
  "failed": 2,
  "cancelled": 1,
  "terminal": 28,
  "success_rate": 89.29,
  "average_duration_ms": 1240.5,
  "average_input_tokens": 120.0,
  "average_output_tokens": 260.0,
  "by_model": [
    {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "total": 20,
      "succeeded": 18,
      "failed": 1,
      "cancelled": 1,
      "running": 0,
      "terminal": 20,
      "success_rate": 90.0,
      "average_duration_ms": 1100.0
    }
  ],
  "errors": [
    {
      "code": "provider_timeout",
      "count": 2
    }
  ]
}
```

安全约束：

- 不返回 Prompt、消息正文、反馈评论、`error_message`、Provider Request ID、用户 ID 或 Run ID；
- 没有 `error_code` 的失败 Run 使用 `unknown`；
- 平均耗时只统计具有合法开始和完成时间的终态 Run；
- 当前 TTS 调用没有持久化审计事件，因此不纳入 AI Run 数量和费用统计。

## 7. 权限与租户隔离

- `admin`：可以查看当前租户全部统计；
- `decision_maker`：可以查看当前租户全部统计；
- `customer_service`、`user`：HTTP 403 `forbidden`；
- 所有 SQL 查询必须显式按当前令牌 `tenant_id` 过滤；
- 其他租户的数据既不返回明细，也不进入分子、分母、趋势和高频问题。

## 8. 错误响应

错误遵守 `API通用响应契约-V0.1.md`：

| HTTP | 错误码 | 条件 |
|---|---|---|
| 401 | 认证领域错误 | 未登录、令牌无效或过期 |
| 403 | `forbidden` | 当前角色不是管理员或决策者 |
| 422 | `validation_error` | 日期格式错误、开始晚于结束、超过 366 天或额外查询参数 |
| 503 | `analytics_unavailable` | 统计数据库查询暂时失败 |

数据库原始异常、SQL、连接串和用户内容不得进入错误响应。

## 9. V0.1 非目标

- 外部 BI、数据仓库、实时流计算和物化视图；
- 自定义租户时区、小时或周粒度；
- 语义聚类高频问题和复杂自然语言分析报告；
- 导出 Excel/PDF、定时邮件和管理大屏轮播；
- TTS 调用次数、音频时长和费用统计；
- 客服个人绩效排名；
- 跨租户平台级运营统计。
