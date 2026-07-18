# 知识文档上传与索引 API 契约（V0.1）

- 制定日期：2026-07-17
- 接口前缀：`/api/v1`
- 关联决策：`DEC-20260717-020`、`DEC-20260717-021`
- 权限：仅租户 `admin`

## 1. 上传文档

```http
POST /api/v1/knowledge/documents
Authorization: Bearer <access-token>
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | binary | 是 | PDF、DOCX 或 UTF-8 TXT，最大 15 MiB |

成功返回 HTTP 202：

```json
{
  "document": {
    "id": "本地文档 UUID",
    "filename": "退款规则.docx",
    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "extension": "docx",
    "size_bytes": 20480,
    "status": "processing",
    "indexing_status": "waiting",
    "latest_error_code": null,
    "completed_at": null,
    "created_at": "2026-07-17T12:00:00Z",
    "updated_at": "2026-07-17T12:00:00Z"
  },
  "job": {
    "id": "本地任务 UUID",
    "document_id": "本地文档 UUID",
    "operation": "upload",
    "status": "processing",
    "indexing_status": "waiting",
    "completed_segments": 0,
    "total_segments": 0,
    "error_code": null,
    "started_at": "2026-07-17T12:00:00Z",
    "completed_at": null,
    "created_at": "2026-07-17T12:00:00Z",
    "updated_at": "2026-07-17T12:00:00Z"
  }
}
```

响应不包含本地存储路径、SHA-256、Dify Dataset ID、Dify Document ID、batch 或 API Key。

## 2. 文档列表与详情

```http
GET /api/v1/knowledge/documents?limit=20&offset=0
GET /api/v1/knowledge/documents/{document_id}
```

列表返回：

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

默认不返回已软删除文档，只返回当前管理员所属租户通过 FastAPI 上传的台账记录。Dify 中预先导入但尚未同步到业务数据库的文档不自动出现在首版列表中。

## 3. 查询索引任务

```http
GET /api/v1/knowledge/jobs/{job_id}
```

当任务仍为 `pending` 或 `processing` 且存在 Dify batch 时，FastAPI 按需刷新 Dify 状态并更新本地台账。

如果 active job 尚未持久化 Dify batch，接口先返回当前本地状态；当该状态持续超过 300 秒时，FastAPI 将文档和任务标记为 `failed`，在响应的 `error_code` 中返回 `knowledge_document_stale_active_job`，并解除该文档的 active job 阻塞。该恢复结果仍使用 HTTP 200 返回任务资源，而不是把已持久化的业务失败改写成 HTTP 5xx。

任务状态：

```text
pending -> processing -> completed
                      -> failed
```

Dify 状态映射：

| Dify 状态 | 平台任务状态 |
|---|---|
| `waiting`、`parsing`、`cleaning`、`splitting`、`indexing`、`paused` | `processing` |
| `completed` | `completed` |
| `error`、`stopped` | `failed` |

## 4. 重新索引

```http
POST /api/v1/knowledge/documents/{document_id}/reindex
```

FastAPI 读取受控本地原文件，通过 Dify 文档 PATCH 文件更新接口创建新 batch。文档已删除、尚无可更新的 Dify 索引、缺少本地文件或存在 active job 时拒绝执行。

成功返回 HTTP 202，结构与上传响应相同，`job.operation=reindex`。

## 5. 删除文档

```http
DELETE /api/v1/knowledge/documents/{document_id}
```

FastAPI 使用以下可恢复顺序执行删除：

1. 删除 Dify 文档；上游返回不存在时按幂等成功处理；
2. 清空本地内部 Dify Document ID，记录 Dify 删除阶段并持久化；
3. 删除受控本地原文件，记录文件删除阶段并持久化；
4. 最后软删除业务文档并完成任务。

如果 Dify 删除成功但本地文件删除失败，本次请求返回脱敏错误并把任务保存为 `failed`；台账不会继续保留已经失效的 Dify Document ID。管理员再次调用 DELETE 时，只继续本地文件和软删除阶段，不重复删除已经完成的上游资源。成功返回 HTTP 202，结构与上传响应相同，`job.operation=delete`，通常任务已经为 `completed`。

## 6. 托管文档检索可见性

本契约中的“托管文档”是指通过 FastAPI 上传、并在 `knowledge_documents` 中保存 Dify Document ID 的文档。知识查询接口获得 Dify 召回记录后，必须在生成 citation 和答案之前应用以下规则：

1. 托管文档只对本地台账中记录的所属租户可见；
2. 已软删除的托管文档对所有租户不可见；
3. Dify 中预先导入、尚未登记到业务台账的教学文档继续作为平台共享文档；
4. 可见性数据库不可用时返回 HTTP 503 和 `knowledge_visibility_unavailable`，不得因为无法判断而直接放行召回记录；
5. 列表、详情、任务和变更接口仍使用本地 `tenant_id` 查询条件；其他租户资源统一表现为 404。

该应用层过滤满足当前单机教学部署的托管文档隔离要求，但不等同于真正的索引级多租户隔离。正式多租户部署仍需评估独立 Dataset 或 Dify metadata 过滤。

## 7. 文件安全规则

1. 只允许 `.pdf`、`.docx`、`.txt`；
2. 文件名不允许 `/`、`\\`、NUL 和控制字符，长度不超过 200；
3. 单文件最大 15 MiB，读取超过上限立即停止；
4. MIME 必须与扩展名允许集合一致；
5. PDF 必须以 `%PDF-` 开头、未加密且 `pypdf` 可解析；
6. DOCX 必须是安全 ZIP，包含 `[Content_Types].xml` 与 `word/document.xml`，成员数量和解压总大小受限，且 `python-docx` 可解析；
7. TXT 必须可按 UTF-8/UTF-8-SIG 解码，不含 NUL，并包含非空文本；
8. 文件正文、解析文本和第三方原始异常不得写入访问日志或错误响应。

## 8. 稳定错误码

| HTTP | 错误码 | 说明 |
|---|---|---|
| 401 | `not_authenticated` / 认证领域错误 | 未登录或令牌无效 |
| 403 | `forbidden` | 非管理员 |
| 404 | `knowledge_document_not_found` | 当前租户文档不存在或已删除 |
| 404 | `knowledge_job_not_found` | 当前租户任务不存在 |
| 409 | `knowledge_document_busy` | 存在 pending/processing 任务 |
| 409 | `knowledge_document_not_indexed` | 文档尚无可更新的 Dify 索引 |
| 409 | `knowledge_document_file_missing` | 重新索引所需本地原文件缺失 |
| 413 | `knowledge_file_too_large` | 超过 15 MiB |
| 415 | `knowledge_file_type_not_supported` | 扩展名或 MIME 不支持 |
| 422 | `knowledge_file_invalid` | 文件名、魔数、ZIP、编码或解析失败 |
| 200（任务失败态） | `knowledge_document_stale_active_job` | 无 batch 的 active job 超过恢复时限，已解除阻塞 |
| 503 | `knowledge_service_not_configured` | Dify Dataset 服务端配置不完整 |
| 503 | `knowledge_storage_unavailable` | 私有文件存储暂时不可用 |
| 503 | `knowledge_document_state_persistence_failed` | 跨系统操作后的文档或任务状态暂时无法持久化 |
| 503 | `knowledge_visibility_unavailable` | 知识查询无法安全完成托管文档租户可见性判断 |
| 502/503/504 | `knowledge_document_upstream_*` | Dify 认证、限流、拒绝、不可用、超时或协议错误 |

所有错误继续使用平台统一错误响应，并且不得返回存储绝对路径、Dify 原始正文或任何凭据。

## 9. V0.1 非目标

- 批量上传；
- 在线预览或下载原文件；
- 杀毒引擎和内容审核平台；
- 对象存储、多节点共享文件系统；
- Celery 自动轮询、Outbox 和后台补偿扫描任务；
- Dify 预置文档自动反向同步；
- 真正的租户级 Dataset 或 metadata 索引隔离。
