# 业务依赖 Compose

`app-compose.yml` 只启动**业务** PostgreSQL 与 Redis，与 Dify 数据卷隔离。

## 启动

在项目根目录：

```bash
docker compose --env-file .env -f deploy/app-compose.yml up -d
docker compose --env-file .env -f deploy/app-compose.yml ps
```

端口来自 `.env`：

- `APP_POSTGRES_PORT`（默认示例 `15432`）
- `APP_REDIS_PORT`（默认示例 `16379`）

均绑定 `127.0.0.1`，降低开发机误暴露风险。

## 与一键脚本关系

`scripts/dev_up.sh` 会调用本 Compose，再执行迁移、演示账号初始化和前后端进程。

Dify 请使用 `dify-self-host/` 下官方 Compose，不要合并进本文件。

## 数据卷

- `app_postgres_data`
- `app_redis_data`

`docker compose stop` 后数据保留；删除卷会清空业务库，操作前请确认。
