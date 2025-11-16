#!/bin/bash
# PostgreSQL backup script for Senex Trader
# Schedule: Daily at 2:00 AM via cron
# Usage: /opt/scripts/backup-postgresql.sh

set -euo pipefail

# Configuration
BACKUP_DIR="/var/backups/postgresql"
DB_NAME="senex_trader"
DB_USER="senex_user"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# S3-compatible storage (optional)
S3_BUCKET="s3://senex-backups-production/postgresql"
RCLONE_REMOTE="s3:senex-backups-production/postgresql"

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting PostgreSQL backup..."

# Perform backup using pg_dump from container
podman exec postgres pg_dump \
    -U "$DB_USER" \
    -F custom \
    -b \
    -v \
    "$DB_NAME" > "${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.backup"

# Compress backup
echo "[$(date)] Compressing backup..."
gzip "${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.backup"

BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.backup.gz"
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)

echo "[$(date)] Backup complete: $BACKUP_FILE ($BACKUP_SIZE)"

# Upload to S3 (if configured)
if command -v rclone &> /dev/null; then
    echo "[$(date)] Uploading to S3..."
    rclone copy "$BACKUP_FILE" "$RCLONE_REMOTE/" --progress
    echo "[$(date)] Upload complete"
fi

# Delete old backups
echo "[$(date)] Cleaning up old backups..."
find "$BACKUP_DIR" -name "${DB_NAME}_*.backup.gz" -mtime +${RETENTION_DAYS} -delete

echo "[$(date)] Backup process complete"

# Verify backup integrity
echo "[$(date)] Verifying backup integrity..."
if gzip -t "$BACKUP_FILE"; then
    echo "[$(date)] Backup file integrity verified"
else
    echo "[$(date)] ERROR: Backup file is corrupted!"
    exit 1
fi
