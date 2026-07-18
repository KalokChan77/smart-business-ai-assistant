# DEC-20260717-008：业务 PostgreSQL 与 Redis 独立于 Dify 部署

- 日期：2026-07-17
- 状态：已接受
- 参与角色：学生开发者、AI 编程助手
- 关联任务：技术方案第二阶段数据库与缓存基础设施
- 关联实习日记：`project_docs/实习日记/2026-07-17-实习日记.md`

## 一、背景

Dify 已经自带 PostgreSQL 和 Redis，但技术方案明确要求 Dify 与业务应用分别维护 Compose。业务系统需要保存用户、角色、会话、消息、工单、反馈和 AI 运行记录，如果直接复用 Dify 内部数据库，会使业务数据与第三方平台升级、迁移和故障相互影响。

## 二、需要解决的问题

需要为 FastAPI 建立独立、可持久化、可健康检查的 PostgreSQL 和 Redis，同时避免与本机已有的 `5432` 端口、Dify 容器和其他项目冲突。

## 三、可选方案

### 方案 A：复用 Dify 的 PostgreSQL 与 Redis

- 优点：少启动两个容器，占用资源较低。
- 缺点：业务系统与 Dify 强耦合，Dify 升级或重建可能影响业务数据，也不利于独立备份和迁移。

### 方案 B：使用本机已有数据库服务

- 优点：不需要新增容器。
- 缺点：已有端口被其他项目占用，权限、数据库名称和生命周期不受当前项目控制。

### 方案 C：单独维护业务 Compose

- 优点：业务数据和 Dify 数据边界清晰，可独立启动、停止、备份和迁移。
- 缺点：增加少量本地资源占用。

## 四、最终决策

创建独立的 `deploy/app-compose.yml`：

- PostgreSQL 使用本机端口 `15432`；
- Redis 使用本机端口 `16379`；
- 两个端口只绑定 `127.0.0.1`，不对局域网或公网开放；
- 密码由本地 `.env` 提供，不写入 Compose 和源码；
- PostgreSQL 与 Redis 使用独立持久化卷；
- 业务 Compose 与 Dify Compose 分开维护。

## 五、决策理由

独立部署符合技术方案的边界要求，也能保证 Dify 停止或升级时业务数据库不受影响。使用非默认端口可以与现有项目并行运行；绑定本机地址能够降低开发环境误开放数据库端口的风险。

## 六、影响与风险

- 正面影响：数据边界清晰，故障和升级互不影响。
- 潜在风险：开发人员启动后端前需要先确认业务 Compose 已运行。
- 回退方案：README 和 readiness 明确报告数据库、Redis 状态；后续应用 Compose 可统一启动业务服务，但仍保持独立容器和数据卷。

## 七、验证证据

- `deploy/app-compose.yml` 通过 Docker Compose 配置校验。
- `smart-business-postgres` 与 `smart-business-redis` 均达到 `healthy` 状态。
- PostgreSQL 绑定 `127.0.0.1:15432`，Redis 绑定 `127.0.0.1:16379`，未对局域网和公网开放。
- FastAPI 真实启动后，readiness 返回 HTTP 200，数据库与 Redis 两个探针均返回 `ok`。
- 业务 PostgreSQL 中存在独立的 `users`、`roles`、`user_roles` 和 `alembic_version` 表，未使用 Dify 数据库。

## 八、后续行动

- [x] 使用 SQLAlchemy 和 Redis 异步客户端接入 FastAPI。
- [x] 运行 Alembic 初始迁移。
- [ ] 后续增加业务数据备份和恢复说明。

## 九、可用于实习日记的素材

我学习到系统集成时不能因为多个组件都使用 PostgreSQL 和 Redis 就直接共用实例。清晰的数据边界可以减少升级和故障影响，也是低耦合架构的重要体现。
