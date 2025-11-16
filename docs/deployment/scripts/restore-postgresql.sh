#!/bin/bash
# PostgreSQL restore script for Senex Trader
# Usage: ./restore-postgresql.sh /path/to/backup.backup.gz

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup-file.backup.gz>"
    echo "Example: $0 /var/backups/postgresql/senextrader_20251008_020000.backup.gz"
    exit 1
fi

BACKUP_FILE="$1"
DB_NAME="senextrader"
DB_USER="senex_user"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "WARNING: This will DROP and recreate the database!"
echo "Database: $DB_NAME"
echo "Backup file: $BACKUP_FILE"
read -p "Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled"
    exit 0
fi

# Uncompress if needed
if [[ "$BACKUP_FILE" == *.gz ]]; then
    echo "Decompressing backup..."
    TEMP_FILE="/tmp/$(basename ${BACKUP_FILE%.gz})"
    gunzip -c "$BACKUP_FILE" > "$TEMP_FILE"
else
    TEMP_FILE="$BACKUP_FILE"
fi

# Stop application containers
echo "Stopping application containers..."
systemctl --user stop django.service celery-worker.service celery-beat.service

# Drop and recreate database
echo "Recreating database..."
podman exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
podman exec postgres psql -U postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

# Restore backup
echo "Restoring backup..."
cat "$TEMP_FILE" | podman exec -i postgres pg_restore \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -v \
    --no-owner \
    --no-acl

# Cleanup temp file if we created one
if [[ "$BACKUP_FILE" == *.gz ]]; then
    rm -f "$TEMP_FILE"
fi

# Start application containers
echo "Starting application containers..."
systemctl --user start django.service celery-worker.service celery-beat.service

echo "Restore complete!"
echo "Verify with: curl http://localhost:8000/health/"
