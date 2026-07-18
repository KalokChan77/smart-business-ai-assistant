#!/usr/bin/env bash
# Stop local FastAPI/Vue dev processes. Business Postgres/Redis stay up by default.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

stop_pidfile() {
  local pidfile="$1"
  local name="$2"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile" || true)"
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "已停止 $name (pid=$pid)"
    fi
    rm -f "$pidfile"
  fi
}

stop_pidfile .tmp/backend.pid "FastAPI"
stop_pidfile .tmp/frontend.pid "Vue3"

if [[ "${STOP_DATA:-0}" == "1" ]]; then
  echo "停止业务 PostgreSQL 与 Redis ..."
  docker compose --env-file .env -f deploy/app-compose.yml stop
else
  echo "业务 PostgreSQL/Redis 保持运行。若要一并停止：STOP_DATA=1 ./scripts/dev_down.sh"
fi

echo "开发进程已停止。"
