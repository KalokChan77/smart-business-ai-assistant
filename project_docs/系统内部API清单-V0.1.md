# 系统内部 API 清单（V0.1）

统一前缀：`/api/v1`

说明：

- 表格中标记“已实现”的接口已经有后端代码和自动化测试；
- 标记“前端已接入”表示 Vue3 页面已调用；
- 标记“浏览器已验证”表示 2026-07-18 四角色真实浏览器冒烟已覆盖主路径；
- 百分比类字段统一按 **0–100** 返回和展示，前端不得再次乘 100；
- `ReplySuggestion.status` 仅有 `draft | confirmed`。

## 健康检查

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| GET | `/health` | 应用存活检查 | 开发联调可用 |
| GET | `/health/ready` | 数据库、Redis 和配置就绪检查 | 开发联调可用 |

## 认证与用户

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| POST | `/auth/login` | 登录并返回 JWT | 已实现并浏览器验证 |
| POST | `/auth/refresh` | 刷新访问令牌 | 请求层已接入（静默刷新） |
| GET | `/auth/me` | 当前用户信息和角色 | 已实现并浏览器验证 |
| POST | `/auth/logout` | 客户端退出及令牌失效记录 | 已实现并浏览器验证 |
| GET | `/users` | 管理员查询用户 | 已实现并浏览器验证 |
| POST | `/users` | 管理员创建用户 | 已实现（管理页接入） |
| PATCH | `/users/{user_id}` | 修改用户和状态 | 已实现（管理页接入） |

## 会话与消息

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| POST | `/conversations` | 创建会话 | 已实现（AI 对话页） |
| GET | `/conversations` | 查询当前用户会话 | 已实现并浏览器验证 |
| GET | `/conversations/{conversation_id}` | 查询会话详情 | 后端已实现 |
| GET | `/conversations/{conversation_id}/messages` | 按位置查询消息列表 | 已实现并浏览器验证 |
| DELETE | `/conversations/{conversation_id}` | 软删除当前用户会话 | 已实现（历史会话页） |

## AI 对话与 Agent

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| POST | `/ai/chat/stream` | 普通模型统一 SSE 流式对话（已实现） | 已实现并浏览器验证（DeepSeek） |
| POST | `/ai/agent/stream` | LangGraph 工具调用与 Agent SSE 流式执行（已实现） | 页面已接入；本轮浏览器主测普通对话 |
| POST | `/ai/cancel/{run_id}` | 取消仍在执行的 AI Run | 后端已实现 |
| GET | `/ai/runs/{run_id}` | 查询当前用户 Chat/Agent Run 状态（已实现） | 后端已实现 |
| POST | `/ai/runs/{run_id}/feedback` | 对当前用户已成功完成的 Run 提交或更新赞踩和文字反馈（已实现） | 已实现；`message_end` 后展示反馈入口并浏览器验证 |

## 知识库

知识文档管理接口均已实现，仅允许当前租户 `admin` 使用。上传、重新索引和删除使用 HTTP 202 表示已创建或完成同步任务；列表、详情和任务查询均按本地租户台账隔离。通过 FastAPI 托管上传的文档还会在知识回答前按租户过滤，删除过程支持分阶段失败恢复。

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| POST | `/knowledge/documents` | 管理员上传 PDF/DOCX/TXT 并创建异步索引任务（已实现） | 管理页已接入 |
| GET | `/knowledge/documents` | 管理员查询当前租户文档台账（已实现） | 已实现并浏览器验证 |
| GET | `/knowledge/documents/{id}` | 管理员查询当前租户文档详情和索引状态（已实现） | 后端已实现 |
| DELETE | `/knowledge/documents/{id}` | 管理员分阶段删除 Dify 索引、本地文件和文档台账，可失败恢复（已实现） | 管理页已接入 |
| POST | `/knowledge/documents/{id}/reindex` | 管理员使用受控原文件重新索引并创建异步任务（已实现） | 管理页已接入 |
| POST | `/knowledge/query` | Dify 知识检索、抽取式安全回答与引用（已实现） | 已实现并浏览器验证 |
| GET | `/knowledge/jobs/{job_id}` | 管理员查询当前租户上传、重建或删除任务状态（已实现） | 管理页任务轮询已接入 |

## 客服辅助

客服辅助六个接口均已实现。普通请求者只能读取自己的公开工单视图，人工确认前看不到 AI 草稿；`customer_service` 与 `admin` 可以读取当前租户内部视图并执行分类、知识增强建议生成和人工确认。数据库使用租户感知复合外键、确认审计约束和统一行锁顺序保证隔离与并发一致性。

契约补充：

- `POST /customer-service/classify` 返回的 `confidence` 为整数 **0–100**；
- 工单字段 `classification_confidence` 同样为 **0–100**；
- `ReplySuggestion.status` 只有 `draft | confirmed`；
- 普通用户公开详情仅在确认后返回 `confirmed_reply.final_reply` 与 `confirmed_at`。

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| GET | `/customer-service/tickets` | 按角色查询当前可见工单的公开列表（已实现） | 已实现并浏览器验证 |
| POST | `/customer-service/tickets` | 当前用户创建自己的工单（已实现） | 已实现并浏览器验证 |
| GET | `/customer-service/tickets/{id}` | 请求者公开详情或客服内部详情；草稿对请求者隐藏（已实现） | 已实现并浏览器验证（用户详情 + 客服详情） |
| POST | `/customer-service/classify` | 客服或管理员执行稳定问题分类（已实现） | 已实现并浏览器验证 |
| POST | `/customer-service/reply-suggestions` | LangGraph 调用知识服务并生成待人工确认建议（已实现） | 已实现并浏览器验证 |
| POST | `/customer-service/reply-suggestions/{id}/confirm` | 客服编辑并在平台内确认最终回复，不调用外部发送渠道（已实现） | 已实现并浏览器验证 |

## 语音

文字转语音接口已实现。任意已登录角色可以提交去除首尾空白后 1～500 字符的文本；FastAPI 使用服务端 Dify Chat App Key 调用已发布的通义 `qwen3-tts-flash`，按文件签名识别 MP3 或 WAV 并返回准确媒体类型。接口限制上游响应为 5 MiB，不持久化音频，并使用 `no-store` 防止缓存。详细契约见 `语音合成API契约-V0.1.md`。

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| POST | `/audio/tts` | 已登录用户将短文本转换为 MP3 或 WAV；Dify 凭据、模型和声音均由服务端管理（已实现） | 对话页已接入 |
| POST | `/audio/asr` | 语音转文字，增强项 | 未实现 |

## 管理配置

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| GET | `/admin/model-configs` | 模型配置列表，不返回真实密钥 | 规划中 |
| PATCH | `/admin/model-configs/{id}` | 修改模型参数 | 规划中 |
| GET | `/admin/prompts` | Prompt 模板和版本 | 规划中 |
| POST | `/admin/prompts` | 创建 Prompt 版本 | 规划中 |
| POST | `/admin/prompts/{id}/publish` | 发布指定 Prompt 版本 | 规划中 |
| GET | `/admin/audit-logs` | 查询管理和 AI 审计日志 | 规划中 |

## 分析统计

五个统计接口均已实现，只允许当前租户的 `admin` 与 `decision_maker` 访问。公共查询参数为可选 `start_date`、`end_date`，按 UTC 自然日首尾包含，默认最近 30 天且最多 366 天。指标由 PostgreSQL 实时聚合，不返回原始工单描述、反馈评论、模型回答或错误正文；无数据时返回 HTTP 200 和完整零值结构。详细口径见 `分析统计API契约-V0.1.md`。

契约补充：

- `satisfaction_rate`、`success_rate`、分类 `percentage` 等字段均为 **0–100**；
- 前端统一使用 `formatPercent` 直接展示，不再乘 100。

| 方法 | 路径 | 用途 | 前端接入 |
|---|---|---|---|
| GET | `/analytics/overview` | 咨询量、已解决、人工接管、满意度、终态 AI 成功率、高频问题和规则摘要（已实现） | 已实现并浏览器验证 |
| GET | `/analytics/consultations` | 按 UTC 日期补零的咨询量趋势（已实现） | 已实现并浏览器验证 |
| GET | `/analytics/categories` | 六个稳定分类与 `unclassified` 的数量和占比（已实现） | 已实现并浏览器验证 |
| GET | `/analytics/satisfaction` | 正面、负面反馈数量及满意度（已实现） | 已实现并浏览器验证 |
| GET | `/analytics/ai-runs` | Run 状态、终态成功率、模型分组、平均耗时、Token 平均值和稳定错误码统计（已实现） | 已实现并浏览器验证 |
