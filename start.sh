#!/bin/sh
# Render free tier: run the queue worker and the API in one web service.
# The worker restarts automatically if it ever exits; the API is the main process.
set -e
cd "$(dirname "$0")/backend"

(
  while true; do
    arq app.worker.WorkerSettings || true
    echo "worker exited; restarting in 3s" >&2
    sleep 3
  done
) &

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
