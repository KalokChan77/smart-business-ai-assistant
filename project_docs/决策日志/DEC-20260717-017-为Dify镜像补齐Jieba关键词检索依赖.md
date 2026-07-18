# DEC-20260717-017：为 Dify 镜像补齐 Jieba 关键词检索依赖

- 日期：2026-07-17
- 状态：已接受
- 参与角色：学生开发者、AI 编程助手
- 关联任务：Dify 三类 Key 验证、economy 知识库召回修复、可重复部署
- 关联实习日记：`project_docs/实习日记/2026-07-17-实习日记.md`

## 一、背景

Dify Chat、Workflow 和 Dataset 三类 Key 已写入根目录 `.env`。验证时，Chat 和 Workflow 可以正常执行，Dataset 列表与目标 Dataset ID 也能够访问，但知识库检索接口虽然返回 HTTP 200，`records` 始终为空。5 份教学文档均为 `completed`，26 个分段全部启用，数据库关键词表也包含当前分段，因此问题不在 Key、文档状态或分段数据。

进一步在 Dify API、Worker 和 WebSocket 容器中检查发现，`langgenius/dify-api:1.15.0` 运行镜像缺少 `jieba`。economy 模式真正执行关键词检索时依赖该包，因此即使文档和关键词表完整，运行镜像仍不具备完整的关键词检索能力。后续还发现，省略 `retrieval_model` 会触发另一个独立的默认检索策略问题，该问题由 `DEC-20260717-018` 单独记录。

## 二、需要解决的问题

1. 如何恢复 economy 关键词检索；
2. 如何避免容器重建后修复丢失；
3. 如何保持 API、Worker、Beat 和 WebSocket 使用同一运行镜像；
4. 如何不直接修改上游主 Compose 文件，便于后续升级 Dify。

## 三、可选方案

### 方案 A：在正在运行的容器中执行 `pip install`

- 优点：恢复速度快。
- 缺点：容器一旦重建就会丢失，无法作为部署成果复现。

### 方案 B：直接修改 Dify 上游 `docker-compose.yaml` 的启动命令

- 优点：不需要构建镜像。
- 缺点：每次启动都可能重复联网安装；污染上游文件；服务启动依赖外部网络，稳定性较差。

### 方案 C：构建本地扩展镜像，并通过独立 Compose 覆盖文件统一替换

- 优点：依赖在镜像构建期固定；容器重建后仍然存在；不修改上游主 Compose；覆盖文件可进入 Git；四类 Python 服务使用同一镜像。
- 缺点：首次构建需要额外时间和本地镜像空间。

## 四、最终决策

- 基于 `langgenius/dify-api:1.15.0` 新建本地扩展镜像；
- 固定安装与上游锁文件一致的 `jieba==0.42.1`；
- 新建可跟踪的 `docker-compose.smart-business.yaml`，为 `api`、`worker`、`worker_beat` 和 `api_websocket` 统一指定 `smart-business/dify-api:1.15.0-jieba`；
- 保留原有共享存储挂载，不在代码、Compose 或日志中写入任何 API Key；
- 新增 `rebuild-local-api.sh`，统一执行配置检查、镜像构建、四类 Python 服务重建、Nginx 上游刷新和健康检查；
- 通过 `docker compose config`、镜像导入检查、容器健康检查和真实 Dataset 检索验证修复。

## 五、决策理由

教学项目强调可重复部署。临时修改运行容器不能证明其他同学或老师重新启动环境后仍可使用，因此必须把依赖固化到镜像和 Compose 配置中。Dify 默认忽略 `docker-compose.override.yaml`，所以本项目使用可跟踪的独立覆盖文件，并由重建脚本显式加载。这样既能与上游主文件分离，也能随项目一起交付。

## 六、影响与风险

- 正面影响：economy 关键词召回可恢复；容器重建不会丢失依赖；四类服务版本一致。
- 资源影响：新增一个本地扩展镜像，首次构建需要下载和安装 Jieba。
- 升级风险：未来 Dify 基础镜像可能已经自带 Jieba，升级时应重新检查并决定是否删除扩展层。
- 供应链控制：依赖固定到明确版本，构建日志和镜像检查只记录包名与版本，不记录凭据。
- 已知提示：Jieba 0.42.1 在 Python 3.12 下会产生部分上游弃用或转义警告，但当前导入和关键词检索功能正常；后续随 Dify 升级重新评估。

## 七、验证要求

- [x] `docker compose config` 能正确合并本地构建配置；
- [x] 本地镜像中可以导入 `jieba`；
- [x] Dify API 和 Worker 重建后保持正常；
- [x] Chat、Workflow、Dataset 三类 Key 验证通过；
- [x] 5 份文档保持 `completed`；
- [x] 退款问题能够召回至少一条记录；
- [x] 未泄露 API Key、Cookie、管理员密码或 Token。

验证证据：

- `docker compose -f docker-compose.yaml -f docker-compose.smart-business.yaml --profile collaboration config --quiet` 通过；
- 本地扩展镜像构建成功，四个 Python 服务均使用 `smart-business/dify-api:1.15.0-jieba`；
- 重建脚本执行后 API 健康状态为 `healthy`，Worker、Beat、WebSocket 和 Nginx 均正常运行；
- 容器内 `jieba` 导入成功；
- Chat API 返回 HTTP 200，Workflow 状态为 `succeeded`，Dataset Key 可访问目标知识库；
- 5 份知识库文档全部为 `completed`；
- 配合 `DEC-20260717-018` 的显式关键词检索参数，退款问题召回 5 条记录。

## 八、后续行动

- [x] 构建并重建 Dify Python 服务；
- [x] 执行三类 Key 与知识库检索验收；
- [x] 将验证结果补充到本决策日志和 2026-07-17 实习日记；
- [ ] 后续 Dify 升级时重新审计该本地镜像层。

## 九、可用于实习日记的素材

这次问题说明 HTTP 200 只能证明接口完成了响应，不能证明业务结果正确。只有继续检查召回数量、文档状态、分段数据和运行依赖，才能发现 economy 检索实际因为缺少 Jieba 而返回空结果。把临时修复固化为本地镜像，也让我理解了“当前容器能运行”和“环境可重复部署”之间的区别。
