#!/bin/sh
set -eu

echo "Applying database migrations..."
python -m alembic upgrade head

if [ "${SKIP_DEMO_SEED:-0}" = "1" ]; then
  echo "Demo account initialization skipped."
elif [ "${DEMO_PASSWORD#replace-with-}" != "${DEMO_PASSWORD}" ]; then
  echo "DEMO_PASSWORD still contains the example placeholder; set a real local password." >&2
  exit 1
elif [ -n "${DEMO_PASSWORD:-}" ]; then
  echo "Creating or refreshing demo accounts..."
  seed_args=""
  if [ "${RESET_DEMO_PASSWORD:-0}" = "1" ]; then
    seed_args="--reset-password"
  fi
  python scripts/bootstrap_demo_tenant.py $seed_args
else
  echo "DEMO_PASSWORD is empty; demo account initialization skipped."
fi

echo "Starting FastAPI..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
