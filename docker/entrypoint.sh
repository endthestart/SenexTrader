#!/bin/bash
set -e

# ============================================================================
# Senex Trader Container Entrypoint
# Routes commands to appropriate services: web, celery-worker, celery-beat
# ============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# Function: Wait for PostgreSQL
# ============================================================================
wait_for_postgres() {
    echo -e "${YELLOW}Waiting for PostgreSQL...${NC}"

    python << END
import sys
import time
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'senex_trader.settings.${ENVIRONMENT:-production}')
django.setup()

from django.db import connection
from django.db.utils import OperationalError

max_retries = 30
retry_interval = 2

for i in range(max_retries):
    try:
        connection.ensure_connection()
        print("PostgreSQL is ready!")
        sys.exit(0)
    except OperationalError as e:
        print(f"PostgreSQL not ready (attempt {i+1}/{max_retries}): {e}")
        time.sleep(retry_interval)

print(f"Failed to connect to PostgreSQL after {max_retries} attempts")
sys.exit(1)
END
}

# ============================================================================
# Function: Wait for Redis
# ============================================================================
wait_for_redis() {
    echo -e "${YELLOW}Waiting for Redis...${NC}"

    python << END
import sys
import time
import redis
import os

redis_url = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
max_retries = 30
retry_interval = 2

for i in range(max_retries):
    try:
        r = redis.from_url(redis_url)
        r.ping()
        print("Redis is ready!")
        sys.exit(0)
    except Exception as e:
        print(f"Redis not ready (attempt {i+1}/{max_retries}): {e}")
        time.sleep(retry_interval)

print(f"Failed to connect to Redis after {max_retries} attempts")
sys.exit(1)
END
}

# ============================================================================
# Main Entrypoint Logic
# ============================================================================

echo -e "${GREEN}Starting Senex Trader container...${NC}"
echo "Command: $1"
echo "Environment: ${ENVIRONMENT:-production}"

# Set Django settings module based on environment (must match celery.py logic)
if [ "${ENVIRONMENT}" = "production" ] || [ "${ENVIRONMENT}" = "staging" ]; then
    export DJANGO_SETTINGS_MODULE="senex_trader.settings.${ENVIRONMENT}"
else
    export DJANGO_SETTINGS_MODULE="senex_trader.settings.development"
fi
echo "Django settings: ${DJANGO_SETTINGS_MODULE}"

# Determine service type from first argument
SERVICE_TYPE="${1:-web}"

# Wait for dependencies (all services need database and Redis)
wait_for_postgres
wait_for_redis

# Run initialization tasks (only for web service to avoid race conditions)
if [ "$SERVICE_TYPE" = "web" ] || [ "$SERVICE_TYPE" = "gunicorn" ] || [ "$SERVICE_TYPE" = "daphne" ]; then
    echo -e "${YELLOW}Running database migrations...${NC}"
    python manage.py migrate --noinput --skip-checks

    echo -e "${YELLOW}Collecting static files...${NC}"
    python manage.py collectstatic --noinput --clear

    echo -e "${GREEN}Initialization complete!${NC}"
fi

# Route to appropriate service
case "$SERVICE_TYPE" in
    web|daphne)
        echo -e "${GREEN}Starting Daphne ASGI server...${NC}"
        exec daphne -b 0.0.0.0 -p 8000 senex_trader.asgi:application
        ;;

    celery-worker|celery_worker|worker)
        echo -e "${GREEN}Starting Celery worker...${NC}"
        exec celery -A senex_trader worker \
            --loglevel=info \
            --queues=celery,accounts,trading \
            --concurrency=4 \
            --max-tasks-per-child=100
        ;;

    celery-beat|celery_beat|beat)
        echo -e "${GREEN}Starting Celery beat scheduler...${NC}"
        # Create celerybeat directory in /tmp (writable by non-root user)
        mkdir -p /tmp/celerybeat
        # Clean up old schedule files (they can become corrupted)
        rm -f /tmp/celerybeat/celerybeat-schedule*
        exec celery -A senex_trader beat \
            --loglevel=info \
            --pidfile=/tmp/celerybeat.pid \
            --schedule=/tmp/celerybeat/celerybeat-schedule
        ;;

    *)
        # Unknown command - pass through to shell
        echo -e "${YELLOW}Running custom command: $@${NC}"
        exec "$@"
        ;;
esac
