#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Docker 业务依赖 =="
if [[ -f .env ]]; then
  docker compose --env-file .env -f deploy/app-compose.yml ps || true
else
  echo ".env 不存在，无法查询 Compose。"
fi
echo
echo "== 本地进程 =="
for name in backend frontend; do
  pidfile=".tmp/${name}.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name: running pid=$(cat "$pidfile")"
  else
    echo "$name: stopped"
  fi
done
echo
echo "== HTTP =="
for url in   http://127.0.0.1:8000/api/v1/health   http://127.0.0.1:8000/api/v1/health/ready   http://127.0.0.1:5173/; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
  echo "$url -> HTTP ${code:-000}"
done
