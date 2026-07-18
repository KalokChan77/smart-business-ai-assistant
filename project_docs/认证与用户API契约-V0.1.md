# 认证与用户 API 契约（V0.1）

- API 前缀：`/api/v1`
- 制定日期：2026-07-17
- 关联决策：DEC-20260717-012、DEC-20260717-013
- 通用错误格式：`project_docs/API通用响应契约-V0.1.md`

## 1. 角色代码

| 角色代码 | 中文名称 | 第一阶段权限 |
|---|---|---|
| `admin` | 管理员 | 管理本租户用户、角色和系统配置 |
| `customer_service` | 客服人员 | 后续访问客服工单和推荐回复 |
| `user` | 企业用户 | 后续访问 AI 对话和知识库问答 |
| `decision_maker` | 决策者 | 后续访问分析统计和 AI 摘要 |

所有角色和用户都属于一个 `tenant_id`。普通用户管理 API 不接受客户端指定目标租户，始终使用当前管理员的租户。

## 2. 登录

### `POST /auth/login`

请求：

```json
{
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "username": "admin",
  "password": "用户输入的密码"
}
```

成功响应：

```json
{
  "access_token": "<JWT>",
  "refresh_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

响应头：

```http
Cache-Control: no-store
Pragma: no-cache
```

用户名会去除首尾空白并转换为小写。密码不会写入日志或错误响应。

## 3. 刷新令牌

### `POST /auth/refresh`

请求：

```json
{
  "refresh_token": "<JWT>"
}
```

成功响应与登录一致，并返回一组新的访问令牌和刷新令牌。

刷新令牌采用轮换策略：旧刷新令牌第一次成功使用后，其 `jti` 会通过 Redis 原子写入吊销标记；再次提交同一个刷新令牌返回 401 `invalid_token`。

## 4. 当前用户

### `GET /auth/me`

请求头：

```http
Authorization: Bearer <access_token>
```

成功响应：

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "username": "admin",
  "email": "admin@example.com",
  "roles": ["admin"]
}
```

服务端不会只相信 JWT 中的角色快照。每个受保护请求都会查询数据库中的当前用户状态和角色，并检查访问令牌是否已在 Redis 中吊销。

## 5. 退出

### `POST /auth/logout`

请求头：

```http
Authorization: Bearer <access_token>
```

请求：

```json
{
  "refresh_token": "<JWT>"
}
```

成功状态：HTTP 204，无响应体。

退出会吊销当前访问令牌和提交的刷新令牌。Redis 只保存格式为 `auth:revoked:<jti>` 的短期标记，并设置为令牌剩余有效期，不保存完整 JWT。

## 6. 查询用户

### `GET /users`

权限：`admin`

返回当前管理员租户内的用户列表。用户对象：

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "username": "demo-user",
  "email": "demo@example.com",
  "status": "active",
  "roles": ["user"],
  "created_at": "2026-07-17T00:00:00Z",
  "updated_at": "2026-07-17T00:00:00Z"
}
```

## 7. 创建用户

### `POST /users`

权限：`admin`

请求：

```json
{
  "username": "demo-user",
  "email": "demo@example.com",
  "password": "至少 8 位密码",
  "role_codes": ["user"]
}
```

成功状态：HTTP 201。

规则：

- 用户名去除首尾空白并转换为小写；
- 邮箱去除首尾空白并转换为小写；
- 用户名和邮箱在同一租户内唯一；
- 至少需要一个已存在角色；
- 密码只保存 Argon2 哈希。

## 8. 修改用户

### `PATCH /users/{user_id}`

权限：`admin`

可修改字段：

```json
{
  "email": "updated@example.com",
  "status": "disabled",
  "role_codes": ["customer_service"]
}
```

至少提交一个字段。管理员不能通过该接口禁用自己的当前账户，也不能移除自己的 `admin` 角色。

目标用户必须属于当前管理员租户；访问其他租户的用户 ID 返回 404，避免暴露跨租户资源是否存在。

## 9. 认证错误码

| HTTP 状态 | 错误码 | 说明 |
|---|---|---|
| 401 | `not_authenticated` | 未提交 Bearer 访问令牌 |
| 401 | `invalid_credentials` | 用户名或密码错误 |
| 401 | `invalid_token` | 令牌无效、过期、类型错误、已吊销或刷新令牌被重复使用 |
| 403 | `user_disabled` | 数据库中的用户状态为禁用 |
| 403 | `forbidden` | 当前数据库角色没有接口权限 |
| 404 | `user_not_found` | 当前租户内不存在目标用户 |
| 409 | `user_conflict` | 同租户用户名或邮箱重复 |
| 409 | `cannot_disable_self` | 管理员尝试禁用自己的当前账户 |
| 409 | `cannot_remove_own_admin_role` | 管理员尝试移除自己的管理员角色 |
| 422 | `roles_required` | 用户没有分配角色 |
| 422 | `unknown_roles` | 请求包含当前租户不存在的角色 |
| 503 | `authentication_not_configured` | JWT 密钥缺失或不符合最低要求 |
| 503 | `authentication_unavailable` | Redis 吊销存储不可用 |

## 10. 首个管理员初始化

首个租户管理员不通过公开 HTTP 接口创建。后端和数据库启动后，在终端执行交互式脚本：

```bash
cd backend
../.venv/bin/python -m scripts.bootstrap_admin
```

脚本通过 `getpass` 读取密码，不把密码显示在终端，也不把密码写入命令行参数、日志或文档。租户 UUID 可以手动输入，也可以留空自动生成。

同一租户一旦已经存在用户，初始化脚本会拒绝再次执行，后续用户必须由已登录管理员通过 `/users` 创建。
