#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

compose=(
  docker compose
  -f docker-compose.yaml
  -f docker-compose.smart-business.yaml
  --profile collaboration
)

"${compose[@]}" config --quiet
"${compose[@]}" build api
"${compose[@]}" up \
  -d \
  --no-deps \
  --force-recreate \
  api worker worker_beat api_websocket

"${compose[@]}" restart nginx

api_container=$("${compose[@]}" ps -q api)
if [[ -z "$api_container" ]]; then
  echo "Dify API container was not created." >&2
  exit 1
fi

health="none"
for _ in $(seq 1 90); do
  health=$(
    docker inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
      "$api_container"
  )
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  sleep 1
done

if [[ "$health" != "healthy" ]]; then
  docker logs --tail 120 "$api_container" >&2
  exit 1
fi

"${compose[@]}" exec -T api \
  /app/api/.venv/bin/python -c 'import jieba; print("jieba import: PASS")'
"${compose[@]}" ps api worker worker_beat api_websocket nginx
