# DEC-20260717-016：采用 LangGraph 状态图编排工具调用 Agent

- 日期：2026-07-17
- 状态：已接受
- 参与角色：学生开发者、AI 编程助手
- 关联任务：首个工具调用 Agent、统一 SSE 事件、AI Run 与会话持久化复用
- 关联实习日记：`project_docs/实习日记/2026-07-17-实习日记.md`

## 一、背景

普通 DeepSeek 和阿里云百炼流式对话已经通过真实验收。技术方案的下一步是引入 LangGraph，使模型能够根据问题选择工具、读取工具结果并继续生成最终回答。当前系统已经拥有 Provider 配置、会话历史、AI Run、SSE、租户权限和消息持久化，Agent 实现必须复用这些能力，而不能另建一套平行的数据和错误协议。

## 二、需要解决的问题

1. LangGraph 类型应放在哪一层，避免污染现有会话和普通模型模块；
2. DeepSeek 与百炼如何提供 LangChain 所需的 `bind_tools` 能力；
3. 图如何限制循环，避免模型反复调用工具；
4. 工具的输入、执行和输出如何保证安全；
5. Agent 中间过程如何映射到已有 SSE 契约；
6. 最终回答、失败和客户端断开如何复用 AI Run 状态机。

## 三、可选方案

### 方案 A：在 FastAPI 路由中手写工具调用循环

- 优点：依赖少，初版代码直观。
- 缺点：模型调用、工具分派、循环控制和状态合并全部耦合在路由中，后续增加节点和人工审批困难。

### 方案 B：扩展普通 `ChatProvider`，让其同时承载 LangChain 消息和工具调用

- 优点：表面上只有一个 Provider 接口。
- 缺点：普通文本流和结构化工具调用的返回模型差异较大，会让已稳定的简单协议承担不相关职责。

### 方案 C：在独立 Agent 领域使用 LangGraph，并为 Agent 提供专用模型工厂

- 优点：LangGraph、LangChain 消息和工具类型只存在于 Agent 模块；会话、AI Run 和 SSE 继续复用稳定的应用服务。
- 缺点：普通 Provider 工厂和 Agent 模型工厂都会读取同一组模型配置，需要明确职责边界。

## 四、最终决策

- 新建 `app/agent/`，集中放置图定义、工具、LangChain 模型工厂、服务、路由和请求模型；
- 普通 `app/ai/providers/` 保持增量文本协议，不加入 LangChain 类型；
- DeepSeek Agent 使用官方 `ChatDeepSeek`，百炼 Agent 使用官方 `ChatQwen`，二者统一暴露 `BaseChatModel.bind_tools`；
- 图使用 `StateGraph(MessagesState)`，流程固定为 `START -> model -> tools 或 END`，工具执行后回到 model；
- 使用 LangGraph `ToolNode` 和 `tools_condition`，不在路由中手写工具分派；
- LangGraph 事件读取固定使用稳定的 `astream_events(version="v2")`；当前依赖中的 v3 协议仍为实验性协议，事件结构与 v2 不兼容，不作为本阶段教学接口基础；
- 第一阶段提供两个无外部副作用的教学工具：安全算术计算、模拟商务政策查询；
- 工具禁止文件写入、Shell、任意网络请求和动态代码执行，算术表达式通过 AST 白名单求值；
- 使用 `recursion_limit` 限制图循环，达到上限时 Run 标记为 `failed`，错误码为 `agent_recursion_limit`；
- Agent SSE 复用 `metadata`、`token`、`message_end`、`error`，新增 `tool_start` 和 `tool_end` 表达可观察的工具步骤；
- 只把最终助手回答保存到 `messages`，中间 ToolMessage 不写入长期会话历史；工具名称和调用次数写入助手消息元数据；
- `AI Run` 新增 `mode=chat|agent`，普通聊天默认 `chat`，Agent 使用 `agent`；
- Agent 继续使用 `(tenant_id, user_id, request_id)` 幂等约束，并复用用户消息先落库、成功后保存完整助手消息、失败不保存半截回答的规则。

## 五、决策理由

LangGraph 的价值是把模型、条件分支和工具执行表示为可测试的状态图。将其限制在独立领域，可以保持普通模型适配器简单，也能让未来加入知识库工具、客服工单工具和人工确认节点时不修改 HTTP 路由。专用模型工厂虽然会读取同一配置，但它只负责构造支持工具调用的 LangChain 模型，职责与增量文本 Provider 不同。

第一阶段工具必须无副作用，可以在不引入审批和补偿事务的情况下验证完整 Agent 循环。等图状态、事件和安全边界稳定后，再通过新的决策日志接入真实业务写操作。

## 六、影响与风险

- 正面影响：Agent 编排、工具注册和普通聊天相互隔离；SSE、权限和持久化保持统一；后续扩展节点时不改路由契约。
- 依赖影响：新增 `langgraph`、`langchain`、`langchain-deepseek` 和 `langchain-qwq`。
- 潜在风险：不同模型的工具调用结构和流式元数据存在差异；模型可能循环调用工具；工具结果可能过长；实验性事件协议可能在小版本中变化。
- 控制措施：统一通过 LangChain 消息对象解析；固定使用 v2 事件协议；设置递归上限；限制工具输入和输出长度；浏览器不接收内部异常和凭据。

## 七、验证要求

- [x] 图单元测试覆盖直接回答、一次工具调用、工具错误和递归上限；
- [x] 算术工具拒绝函数调用、属性访问和超限计算；
- [x] SSE 测试覆盖 `tool_start`、`tool_end`、`message_end` 与 `error`；
- [x] Agent 成功时只保存用户消息和最终助手消息；
- [x] Agent 失败或取消时不保存不完整助手消息；
- [x] `AI Run.mode` 迁移可升级、降级并通过约束测试；
- [x] DeepSeek 完成一次真实工具调用冒烟；
- [x] 全量测试、编译和依赖检查通过。

验证证据：

- LangGraph 图、工具、服务和 Agent API 定向测试全部通过；
- 全量自动化测试共 72 项通过，`compileall` 和 `pip check` 通过；
- `alembic check` 无新增迁移，在临时 PostgreSQL 数据库完成全量升级、最新迁移降级和再次升级；
- 真实 DeepSeek Agent 调用成功产生 `metadata`、`tool_start`、`tool_end`、`token` 和 `message_end`，Run 持久化为 `mode=agent`、`status=succeeded`；
- 长期会话只包含一条用户消息和一条最终助手消息，中间工具消息未落库；
- 冒烟测试结束后，临时用户、会话、AI Run 和 Redis 测试键均为 0。

## 八、后续行动

- [x] 安装并锁定 LangGraph 相关依赖；
- [x] 实现 Agent 模型工厂和安全工具注册表；
- [x] 实现状态图、Agent 服务和 `/api/v1/ai/agent/stream`；
- [x] 更新 AI SSE API 契约、内部 API 清单和实习日记；
- [ ] 普通工具 Agent 稳定后，再进入 Dify 统一编排或 RAG 文档阶段。

## 九、可用于实习日记的素材

我认识到 Agent 不是在普通对话后面简单增加一个工具函数，而是一个有状态、有分支、可能循环的执行过程。使用 LangGraph 可以把模型判断、工具执行和结束条件明确表示出来。把 LangGraph 类型限制在独立模块，并复用已有会话、Run 和 SSE 服务，能够减少框架对核心业务的侵入，也更符合高内聚、低耦合原则。
