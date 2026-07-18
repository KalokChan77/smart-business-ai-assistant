#!/usr/bin/env bash
# Start local teaching stack: business PostgreSQL/Redis, migrate, backend, frontend.
# Dify remains a separate Compose stack under dify-self-host/.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "缺少 .env。请先复制 .env.example 并填写密钥："
  echo "  cp .env.example .env"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "缺少 Python 虚拟环境 .venv。请先执行 README 中的安装步骤。"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 docker 命令。"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "未找到 npm 命令。"
  exit 1
fi

echo "[1/5] 启动业务 PostgreSQL 与 Redis ..."
docker compose --env-file .env -f deploy/app-compose.yml up -d

echo "[2/5] 等待数据库健康检查 ..."
database_ready=0
for _ in $(seq 1 60); do
  if docker compose --env-file .env -f deploy/app-compose.yml ps --status running | grep -q smart-business-postgres; then
    if docker exec smart-business-postgres pg_isready >/dev/null 2>&1; then
      database_ready=1
      break
    fi
  fi
  sleep 1
done
if [[ "$database_ready" != "1" ]]; then
  echo "业务 PostgreSQL 在 60 秒内未就绪。"
  docker compose --env-file .env -f deploy/app-compose.yml ps
  exit 1
fi

echo "[3/5] 执行数据库迁移 ..."
(
  cd backend
  ../.venv/bin/alembic upgrade head
)

if [[ "${SKIP_DEMO_SEED:-0}" != "1" ]]; then
  echo "[4/5] 初始化/刷新演示账号 ..."
  if [[ -z "${DEMO_PASSWORD:-}" ]]; then
    echo "提示：未设置 DEMO_PASSWORD 时将交互输入；可 export DEMO_PASSWORD=... 或 SKIP_DEMO_SEED=1 跳过。"
  fi
  seed_args=()
  if [[ -n "${DEMO_TENANT_ID:-}" ]]; then
    seed_args+=(--tenant-id "$DEMO_TENANT_ID")
  fi
  if [[ "${RESET_DEMO_PASSWORD:-0}" == "1" ]]; then
    seed_args+=(--reset-password)
  fi
  .venv/bin/python backend/scripts/bootstrap_demo_tenant.py "${seed_args[@]}"
else
  echo "[4/5] 跳过演示账号初始化（SKIP_DEMO_SEED=1）"
fi

echo "[5/5] 启动 FastAPI 与 Vue3 开发服务 ..."
mkdir -p .tmp
BACKEND_LOG=".tmp/backend-dev.log"
FRONTEND_LOG=".tmp/frontend-dev.log"

if [[ ! -d frontend/node_modules ]]; then
  echo "安装前端依赖 ..."
  (cd frontend && npm ci)
fi

# Stop previous processes managed by this script.
for pidfile in .tmp/backend.pid .tmp/frontend.pid; do
  if [[ -f "$pidfile" ]]; then
    old_pid="$(cat "$pidfile" || true)"
    if [[ -n "${old_pid}" ]] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
done

for port in 8000 5173; do
  if command -v lsof >/dev/null 2>&1 && lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "端口 $port 已被其他进程占用。请先处理该进程，再重新启动。"
    exit 1
  fi
done

(
  cd backend
  nohup ../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 \
    >"../$BACKEND_LOG" 2>&1 &
  echo $! >"../.tmp/backend.pid"
)

(
  cd frontend
  nohup npm run dev >"../$FRONTEND_LOG" 2>&1 &
  echo $! >"../.tmp/frontend.pid"
)

wait_for_http() {
  local name="$1"
  local url="$2"
  local log_file="$3"
  for _ in $(seq 1 60); do
    if curl --fail --silent --output /dev/null "$url"; then
      return 0
    fi
    sleep 1
  done
  echo "$name 在 60 秒内未就绪。最近日志："
  tail -n 30 "$log_file" 2>/dev/null || true
  return 1
}

wait_for_http "FastAPI" "http://127.0.0.1:8000/api/v1/health" "$BACKEND_LOG"
wait_for_http "Vue3" "http://127.0.0.1:5173/" "$FRONTEND_LOG"

echo
echo "本地开发栈已启动："
echo "  前端: http://127.0.0.1:5173"
echo "  后端: http://127.0.0.1:8000/docs"
echo "  健康: http://127.0.0.1:8000/api/v1/health"
echo "  就绪: http://127.0.0.1:8000/api/v1/health/ready"
echo "  后端日志: $BACKEND_LOG"
echo "  前端日志: $FRONTEND_LOG"
echo
echo "停止：./scripts/dev_down.sh"
echo "Dify 仍使用独立目录 dify-self-host/ 的 Compose，不并入本脚本。"
