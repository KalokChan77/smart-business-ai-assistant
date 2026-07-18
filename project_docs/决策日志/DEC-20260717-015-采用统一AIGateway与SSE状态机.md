# DEC-20260717-015：采用统一 AI Gateway 与 SSE 状态机

- 日期：2026-07-17
- 状态：已接受
- 参与角色：学生开发者、AI 编程助手
- 关联任务：DeepSeek、阿里云百炼普通模型流式对话，AI Run 追踪与消息持久化
- 关联实习日记：`project_docs/实习日记/2026-07-17-实习日记.md`

## 一、背景

会话和消息持久化已经完成，下一阶段需要接入 DeepSeek 与阿里云百炼。若路由直接调用各厂商 SDK，鉴权、流解析、错误处理、消息保存和运行状态会重复散落，后续接入 LangGraph 或 Dify 时也难以复用。

## 二、最终决策

- 在 `app/ai/` 建立独立 AI Gateway 领域，Provider 只负责把统一消息转换为厂商请求并输出增量文本；
- DeepSeek 使用异步 HTTP OpenAI 兼容流式接口；百炼使用 `dashscope.AioGeneration`；厂商 SDK 不进入路由和会话领域；
- SSE 固定使用四类事件：`metadata`、`token`、`message_end`、`error`；
- `metadata` 只发送一次，`token` 可发送多次，成功时只发送一次 `message_end`，失败时只发送一次 `error`，两种终止事件互斥；
- 流开始前创建 `AI Run` 并保存用户消息；模型正常结束后才把拼接后的完整助手回复一次性保存；不逐 Token 写数据库；
- Provider 中途失败时将 Run 标记为 `failed`，保留用户消息，不保存不完整助手消息；客户端断开时标记为 `cancelled`；
- `AI Run` 记录租户、用户、会话、Provider、模型、请求 ID、用户消息 ID、助手消息 ID、状态、Token 用量和安全错误码；
- `(tenant_id, user_id, request_id)` 唯一，重复的客户端 `X-Request-ID` 返回冲突，防止重试重复写入用户消息；
- API 不允许客户端任意指定模型名，只允许选择已配置 Provider，具体模型由服务端环境变量控制；
- Provider 原始错误、响应体和凭据不发送给浏览器，也不写入业务数据；浏览器只收到稳定安全错误码。

## 三、理由与权衡

Provider 协议降低厂商耦合，SSE 状态机让前端能够统一处理不同模型。两阶段持久化能保留用户真实问题，同时避免把半截回答伪装成完整历史。逐 Token 落库虽然恢复粒度更细，但会造成大量写入、重复片段和复杂事务，不符合当前教学规模。

同一会话内仍由 DEC-014 的行锁和 `position` 分配保证消息顺序。AI Run 使用请求 ID 幂等，解决浏览器重试导致的重复请求问题；第一阶段不实现断点续传，重复请求返回已有运行冲突，前端可进一步查询 Run 状态。

## 四、风险

- 长连接期间数据库会话生命周期更长，需要确保 Provider 等待期间不持有数据库行锁；
- 助手消息保存和 Run 成功状态是两个持久化动作，极端数据库故障下可能需要后台补偿；
- 客户端断开依赖 ASGI 取消信号，不同代理层的断开检测时间可能不同；
- 当前只保存完整助手回复，不支持恢复已发送但未完成的 Token。

## 五、验证要求

- [x] DeepSeek 与 DashScope 适配器分别通过增量解析和错误映射测试；
- [x] SSE 测试证明事件顺序和终止事件互斥；
- [x] Provider 中途失败时 Run 为 `failed`，只有用户消息；
- [x] 正常结束时 Run 为 `succeeded`，完整助手消息只保存一次；
- [x] 重复请求 ID 被阻止；
- [x] 非本人 Run 不可查询；
- [x] 客户端取消时 Run 收敛为 `cancelled`；
- [x] Alembic 往返、56 项全量测试、DeepSeek 与百炼真实模型冒烟全部通过。

## 六、后续行动

- [x] 实现 AI Run 模型、仓储和迁移。
- [x] 实现统一 Provider 协议、DeepSeek 和 DashScope 适配器。
- [x] 实现 `/api/v1/ai/chat/stream` 与 `/api/v1/ai/runs/{run_id}`。
- [x] 编写 AI SSE API 契约并回填实习日记。
- [ ] 普通模型链路稳定后再进入 LangGraph，不提前混入工具调用。

## 七、最终验证证据

- 新增迁移 `ebe76b2f44f6_create_ai_runs.py`，上游为 `208539977b2b`；
- 迁移创建 AI Run 状态约束、Token 非负约束、所有者请求 ID 唯一约束和所有者/会话索引；
- 56 项自动化测试全部通过，包含 Provider、SSE、取消、幂等、所有者隔离和 PostgreSQL 约束测试；
- Python `compileall`、`pip check` 和两次 `alembic check` 通过；迁移完成降级、再次升级；
- 真实百炼 `qwen-plus` 冒烟成功，SSE 顺序为 `metadata`、`token`、`message_end`，完整助手消息和 succeeded Run 均已验证；
- DeepSeek 使用轮换后的新密钥完成真实冒烟，SSE 顺序为 `metadata`、`token`、`message_end`，回答完整落库且 Run 状态为 `succeeded`；
- DeepSeek 与百炼真实冒烟产生的临时用户、会话、AI Run 和 Redis 吊销键均清理为 0。
