#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env without exporting comments
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -o allexport
  # shellcheck source=/dev/null
  source "$PROJECT_ROOT/.env"
  set +o allexport
fi

# Clean up stale Celery Beat schedule files to ensure fresh schedule from Python config
# Beat caches its schedule in SQLite files which can become outdated when celery.py changes
echo "Cleaning up stale Celery Beat schedule files..."
rm -f celerybeat-schedule celerybeat-schedule.db celerybeat-schedule.dat
rm -f celerybeat-schedule.dir celerybeat-schedule-shm celerybeat-schedule-wal

# Listen to all application queues: default celery queue + routed queues
QUEUES="${CELERY_QUEUES:-celery,accounts,trading}"

WORKER_CMD=(celery -A senextrader worker --loglevel=info --queues="$QUEUES")
BEAT_CMD=(celery -A senextrader beat --loglevel=info)

echo "Starting Celery worker (queues: $QUEUES)"
echo "Starting Celery beat scheduler"
echo "==================== CELERY OUTPUT ===================="
echo ""

# Run both processes in foreground with output to console
"${WORKER_CMD[@]}" &
WORKER_PID=$!

"${BEAT_CMD[@]}" &
BEAT_PID=$!

cleanup() {
  echo "\nShutting down Celery processes..."
  kill "$WORKER_PID" "$BEAT_PID" >/dev/null 2>&1 || true
  wait "$WORKER_PID" "$BEAT_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

# Wait for any process to exit, then trigger cleanup via trap
wait -n "$WORKER_PID" "$BEAT_PID"
