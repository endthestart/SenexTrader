# Backup and Disaster Recovery

## Overview

**Recovery Objectives**:
- **RTO (Recovery Time Objective)**: 30 minutes
- **RPO (Recovery Point Objective)**: 5 minutes
- **Data Retention**: 30 days (PostgreSQL), 7 days (Redis)

**Backup Types**:
1. **PostgreSQL**: WAL archiving + base backups (PITR capability)
2. **Redis**: RDB snapshots + AOF log
3. **Media Files**: rsync to S3-compatible storage
4. **Configuration**: Git version control

## PostgreSQL Backup Strategy

### Point-in-Time Recovery (PITR) Setup

**1. Enable WAL Archiving**:

Edit PostgreSQL Quadlet file or pass as exec arguments:

```ini
Exec=postgres \
  -c wal_level=replica \
  -c archive_mode=on \
  -c archive_command='test ! -f /var/backups/postgresql/wal_archive/%f && cp %p /var/backups/postgresql/wal_archive/%f' \
  -c archive_timeout=300 \
  -c max_wal_senders=3 \
  -c wal_keep_size=1GB
```

**2. Create archive directory**:

```bash
sudo mkdir -p /var/backups/postgresql/{wal_archive,base_backups}
sudo chown -R senex:senex /var/backups/postgresql
chmod 700 /var/backups/postgresql
```

**3. Mount archive volume in Quadlet**:

```ini
Volume=/var/backups/postgresql/wal_archive:/var/backups/postgresql/wal_archive:z
```

### Base Backup Script

**File**: `/opt/scripts/backup-postgresql.sh` (already created, enhanced version):

```bash
#!/bin/bash
set -euo pipefail

# Configuration
BACKUP_BASE_DIR="/var/backups/postgresql/base_backups"
WAL_ARCHIVE_DIR="/var/backups/postgresql/wal_archive"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_BASE_DIR}/${TIMESTAMP}"

# S3 configuration
S3_BUCKET="${S3_BUCKET:-s3://senex-backups-production}"
RCLONE_REMOTE="${RCLONE_REMOTE:-s3:senex-backups-production}"

# Logging
LOG_FILE="/var/log/backups-postgresql.log"
exec 1> >(tee -a "$LOG_FILE")
exec 2>&1

echo "[$(date)] === Starting PostgreSQL backup ==="

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Perform base backup using pg_basebackup
echo "[$(date)] Creating base backup..."
podman exec postgres pg_basebackup \
    -U postgres \
    -D /tmp/basebackup \
    -F tar \
    -z \
    -P \
    -R

# Copy backup from container to host
podman cp postgres:/tmp/basebackup/base.tar.gz "${BACKUP_DIR}/base.tar.gz"
podman cp postgres:/tmp/basebackup/pg_wal.tar.gz "${BACKUP_DIR}/pg_wal.tar.gz"

# Create backup manifest
cat > "${BACKUP_DIR}/manifest.txt" << EOF
Backup Date: $(date -Iseconds)
Backup Type: pg_basebackup
PostgreSQL Version: $(podman exec postgres psql -U postgres -t -c 'SELECT version();')
Database Size: $(podman exec postgres psql -U postgres -t -c "SELECT pg_size_pretty(pg_database_size('senextrader'));")
WAL Archive Location: ${WAL_ARCHIVE_DIR}
EOF

# Calculate checksum
cd "$BACKUP_DIR"
sha256sum *.tar.gz > checksums.sha256

BACKUP_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
echo "[$(date)] Base backup complete: $BACKUP_SIZE"

# Upload to S3 (if configured)
if command -v rclone &> /dev/null && [ -n "$RCLONE_REMOTE" ]; then
    echo "[$(date)] Uploading to S3..."
    rclone sync "$BACKUP_DIR" "${RCLONE_REMOTE}/postgresql/base/${TIMESTAMP}/" \
        --progress \
        --transfers=4 \
        --checkers=8
    
    # Upload WAL archive
    rclone sync "$WAL_ARCHIVE_DIR" "${RCLONE_REMOTE}/postgresql/wal_archive/" \
        --progress
    
    echo "[$(date)] S3 upload complete"
fi

# Clean up old backups (local)
echo "[$(date)] Cleaning old local backups (>${RETENTION_DAYS} days)..."
find "$BACKUP_BASE_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +${RETENTION_DAYS} -exec rm -rf {} \;

# Clean up old WAL archives (keep in sync with base backups)
OLDEST_BACKUP=$(ls -1 "$BACKUP_BASE_DIR" | head -1)
if [ -n "$OLDEST_BACKUP" ]; then
    OLDEST_WAL=$(cat "${BACKUP_BASE_DIR}/${OLDEST_BACKUP}/manifest.txt" | grep -oP '(?<=Oldest WAL: )\w+' || echo "")
    if [ -n "$OLDEST_WAL" ]; then
        echo "[$(date)] Cleaning WAL archives older than $OLDEST_WAL..."
        find "$WAL_ARCHIVE_DIR" -type f -name "0*" ! -newer "${WAL_ARCHIVE_DIR}/${OLDEST_WAL}" -delete
    fi
fi

# Verify backup integrity
echo "[$(date)] Verifying backup integrity..."
cd "$BACKUP_DIR"
if sha256sum -c checksums.sha256 > /dev/null 2>&1; then
    echo "[$(date)] ✓ Backup integrity verified"
else
    echo "[$(date)] ✗ ERROR: Backup integrity check failed!"
    exit 1
fi

echo "[$(date)] === Backup complete ==="
echo "Backup location: $BACKUP_DIR"
echo "Backup size: $BACKUP_SIZE"
```

**Schedule daily backups**:

```bash
# Crontab for senex user
0 2 * * * /opt/scripts/backup-postgresql.sh

# Or systemd timer (preferred)
# Create: ~/.config/systemd/user/postgresql-backup.timer
```

### Point-in-Time Recovery Procedure

**Restore to specific timestamp**:

```bash
#!/bin/bash
# /opt/scripts/restore-postgresql-pitr.sh

RESTORE_TIMESTAMP="$1"  # Format: 2025-10-08 14:30:00
BACKUP_DIR="$2"  # Base backup directory

if [ -z "$RESTORE_TIMESTAMP" ] || [ -z "$BACKUP_DIR" ]; then
    echo "Usage: $0 'YYYY-MM-DD HH:MM:SS' /path/to/base/backup"
    exit 1
fi

echo "WARNING: This will STOP and REPLACE the current database!"
echo "Restore timestamp: $RESTORE_TIMESTAMP"
echo "Backup directory: $BACKUP_DIR"
read -p "Continue? (type 'yes'): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelled"
    exit 0
fi

# Stop dependent services
echo "Stopping services..."
systemctl --user stop django celery-worker celery-beat

# Stop PostgreSQL
podman stop postgres

# Remove old data
echo "Removing old data directory..."
podman volume rm postgres_data -f
podman volume create postgres_data

# Extract base backup
echo "Restoring base backup..."
tar -xzf "${BACKUP_DIR}/base.tar.gz" -C /tmp/restore
tar -xzf "${BACKUP_DIR}/pg_wal.tar.gz" -C /tmp/restore/pg_wal

# Create recovery configuration
cat > /tmp/restore/recovery.signal << EOF
restore_command = 'cp /var/backups/postgresql/wal_archive/%f %p'
recovery_target_time = '$RESTORE_TIMESTAMP'
recovery_target_action = 'promote'
EOF

# Copy restored data to volume
# (Implementation depends on volume backend)

# Start PostgreSQL in recovery mode
podman start postgres

# Monitor recovery
echo "Monitoring recovery progress..."
while true; do
    STATUS=$(podman exec postgres psql -U postgres -t -c "SELECT pg_is_in_recovery();")
    if [ "$STATUS" = " f" ]; then
        echo "Recovery complete! Database is now in normal operation."
        break
    fi
    echo "Still recovering..."
    sleep 5
done

# Restart services
systemctl --user start django celery-worker celery-beat

echo "Point-in-time recovery complete!"
```

## Redis Backup

### RDB Snapshots

**Automated via Redis configuration** (already in redis.conf):

```conf
save 900 1
save 300 10
save 60 10000
```

**Manual snapshot**:

```bash
podman exec redis redis-cli -a PASSWORD BGSAVE
```

**Backup script** (`/opt/scripts/backup-redis.sh`):

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/var/backups/redis"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Triggering Redis BGSAVE..."
podman exec redis redis-cli -a "${REDIS_PASSWORD}" BGSAVE

# Wait for save to complete
while true; do
    LASTSAVE=$(podman exec redis redis-cli -a "${REDIS_PASSWORD}" LASTSAVE)
    sleep 1
    NEWSAVE=$(podman exec redis redis-cli -a "${REDIS_PASSWORD}" LASTSAVE)
    [ "$LASTSAVE" != "$NEWSAVE" ] && break
done

# Copy RDB file
podman cp redis:/data/dump.rdb "${BACKUP_DIR}/dump_${TIMESTAMP}.rdb"

# Copy AOF file
podman cp redis:/data/appendonly.aof "${BACKUP_DIR}/appendonly_${TIMESTAMP}.aof"

# Compress
gzip "${BACKUP_DIR}/dump_${TIMESTAMP}.rdb"
gzip "${BACKUP_DIR}/appendonly_${TIMESTAMP}.aof"

# Upload to S3
if command -v rclone &> /dev/null; then
    rclone copy "${BACKUP_DIR}/dump_${TIMESTAMP}.rdb.gz" "${RCLONE_REMOTE}/redis/"
    rclone copy "${BACKUP_DIR}/appendonly_${TIMESTAMP}.aof.gz" "${RCLONE_REMOTE}/redis/"
fi

# Clean old backups
find "$BACKUP_DIR" -name "*.rdb.gz" -mtime +${RETENTION_DAYS} -delete
find "$BACKUP_DIR" -name "*.aof.gz" -mtime +${RETENTION_DAYS} -delete

echo "[$(date)] Redis backup complete"
```

**Schedule hourly**:

```bash
0 * * * * /opt/scripts/backup-redis.sh
```

### Redis Restore

```bash
#!/bin/bash
# /opt/scripts/restore-redis.sh

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Stop services
systemctl --user stop django celery-worker celery-beat
podman stop redis

# Decompress if needed
if [[ "$BACKUP_FILE" == *.gz ]]; then
    gunzip -c "$BACKUP_FILE" > /tmp/dump.rdb
    RESTORE_FILE="/tmp/dump.rdb"
else
    RESTORE_FILE="$BACKUP_FILE"
fi

# Copy to Redis data volume
podman cp "$RESTORE_FILE" redis:/data/dump.rdb

# Start Redis
podman start redis

# Wait for Redis to load data
sleep 5

# Verify data loaded
KEYS_COUNT=$(podman exec redis redis-cli -a "${REDIS_PASSWORD}" DBSIZE)
echo "Restored database contains $KEYS_COUNT keys"

# Restart services
systemctl --user start django celery-worker celery-beat

echo "Redis restore complete"
```

## Media Files Backup

**Script** (`/opt/scripts/backup-media.sh`):

```bash
#!/bin/bash
set -euo pipefail

MEDIA_DIR="/home/senex/senex-trader/media"
BACKUP_DIR="/var/backups/media"
TIMESTAMP=$(date +%Y%m%d)

# Incremental backup using rsync
rsync -avz --delete \
    "$MEDIA_DIR/" \
    "${BACKUP_DIR}/media_${TIMESTAMP}/" \
    --link-dest="${BACKUP_DIR}/media_latest/"

# Update latest symlink
ln -snf "${BACKUP_DIR}/media_${TIMESTAMP}" "${BACKUP_DIR}/media_latest"

# Sync to S3
rclone sync "${BACKUP_DIR}/media_latest/" "${RCLONE_REMOTE}/media/" \
    --progress \
    --fast-list

echo "Media backup complete"
```

## Backup Verification

### Automated Testing

**Script** (`/opt/scripts/test-backup-restore.sh`):

```bash
#!/bin/bash
# Test restore in isolated environment

TEST_CONTAINER="postgres-restore-test"
BACKUP_DIR="$1"

# Create test container
podman run -d \
    --name "$TEST_CONTAINER" \
    -e POSTGRES_PASSWORD=test \
    postgres:16

# Wait for startup
sleep 10

# Restore backup
tar -xzf "${BACKUP_DIR}/base.tar.gz" -C /tmp/test-restore

# Verify data integrity
podman exec "$TEST_CONTAINER" psql -U postgres -c "\dt"

# Cleanup
podman rm -f "$TEST_CONTAINER"

echo "Backup verification complete"
```

**Schedule monthly**:

```bash
0 3 1 * * /opt/scripts/test-backup-restore.sh /var/backups/postgresql/base_backups/latest
```

## Disaster Recovery Procedures

### Scenario 1: Database Corruption

**Symptoms**:
- PostgreSQL won't start
- Data inconsistency errors
- Corruption detected in logs

**Recovery**:

```bash
# 1. Stop all services
systemctl --user stop django celery-worker celery-beat
podman stop postgres

# 2. Restore from most recent base backup
/opt/scripts/restore-postgresql-pitr.sh "$(date -d '1 hour ago' '+%Y-%m-%d %H:%M:%S')" \
    /var/backups/postgresql/base_backups/latest

# 3. Verify data integrity
podman exec postgres psql -U senex_user -d senextrader -c "SELECT COUNT(*) FROM trading_position;"

# 4. Restart services
systemctl --user start django celery-worker celery-beat
```

### Scenario 2: Complete Server Failure

**Prerequisites**:
- Offsite backups (S3)
- Infrastructure automation (Ansible)
- Documented recovery procedures

**Recovery Steps**:

1. **Provision new server** (15 minutes):
```bash
# Using infrastructure as code
terraform apply -var="environment=production-dr"
```

2. **Deploy application** (10 minutes):
```bash
ansible-playbook -i inventory/production-dr/hosts.yml site.yml \
    --vault-password-file ~/.vault_pass_production
```

3. **Restore data** (15 minutes):
```bash
# Download from S3
rclone sync s3:senex-backups-production/postgresql/base/latest/ \
    /var/backups/postgresql/base_backups/latest/

rclone sync s3:senex-backups-production/postgresql/wal_archive/ \
    /var/backups/postgresql/wal_archive/

# Restore PostgreSQL
/opt/scripts/restore-postgresql-pitr.sh "latest" \
    /var/backups/postgresql/base_backups/latest

# Restore Redis
rclone copy s3:senex-backups-production/redis/latest.rdb.gz /tmp/
/opt/scripts/restore-redis.sh /tmp/latest.rdb.gz

# Restore media
rclone sync s3:senex-backups-production/media/ \
    /home/senex/senex-trader/media/
```

4. **Update DNS** (5 minutes):
```bash
# Update A record to point to new server IP
# TTL is 300s (5 minutes), so propagation is fast
```

5. **Verify and monitor** (5 minutes):
```bash
# Run health check
/opt/scripts/health-check.sh

# Monitor logs
journalctl --user -u django -f
```

**Total Recovery Time**: ~50 minutes (within 30-minute RTO if automated)

### Scenario 3: Accidental Data Deletion

**Recovery**:

```bash
# Restore to point before deletion
DELETION_TIME="2025-10-08 14:25:00"  # 5 minutes before deletion noticed

/opt/scripts/restore-postgresql-pitr.sh \
    "$(date -d '5 minutes ago' '+%Y-%m-%d %H:%M:%S')" \
    /var/backups/postgresql/base_backups/latest
```

## Backup Monitoring

### Verify Backups Exist

**Script** (`/opt/scripts/check-backups.sh`):

```bash
#!/bin/bash

ERRORS=0

# Check PostgreSQL base backup
LATEST_BACKUP=$(ls -t /var/backups/postgresql/base_backups/ | head -1)
BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "/var/backups/postgresql/base_backups/$LATEST_BACKUP")) / 3600 ))

if [ $BACKUP_AGE -gt 26 ]; then
    echo "ERROR: Latest PostgreSQL backup is ${BACKUP_AGE}h old (>26h)"
    ERRORS=$((ERRORS + 1))
else
    echo "OK: PostgreSQL backup is ${BACKUP_AGE}h old"
fi

# Check WAL archives
WAL_COUNT=$(find /var/backups/postgresql/wal_archive/ -type f -mmin -360 | wc -l)
if [ $WAL_COUNT -lt 1 ]; then
    echo "ERROR: No recent WAL archives (last 6h)"
    ERRORS=$((ERRORS + 1))
else
    echo "OK: ${WAL_COUNT} WAL archives in last 6h"
fi

# Check Redis backup
LATEST_REDIS=$(ls -t /var/backups/redis/dump_*.rdb.gz | head -1)
REDIS_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_REDIS")) / 3600 ))

if [ $REDIS_AGE -gt 2 ]; then
    echo "ERROR: Latest Redis backup is ${REDIS_AGE}h old (>2h)"
    ERRORS=$((ERRORS + 1))
else
    echo "OK: Redis backup is ${REDIS_AGE}h old"
fi

# Check S3 sync
if command -v rclone &> /dev/null; then
    S3_CHECK=$(rclone lsd "${RCLONE_REMOTE}/postgresql/base/" | wc -l)
    if [ $S3_CHECK -lt 1 ]; then
        echo "ERROR: No backups in S3"
        ERRORS=$((ERRORS + 1))
    else
        echo "OK: Backups present in S3"
    fi
fi

if [ $ERRORS -gt 0 ]; then
    echo "FAILED: $ERRORS backup checks failed"
    exit 1
else
    echo "SUCCESS: All backup checks passed"
    exit 0
fi
```

**Schedule daily**:

```bash
0 9 * * * /opt/scripts/check-backups.sh | mail -s "Backup Check Report" admin@your-domain.com
```

## Backup Best Practices

1. **3-2-1 Rule**:
   - 3 copies of data
   - 2 different media types
   - 1 offsite copy

2. **Test Restores**:
   - Monthly automated tests
   - Quarterly manual full restore drill

3. **Monitor Backup Jobs**:
   - Alert on backup failures
   - Verify backup sizes (detect incomplete backups)

4. **Document Procedures**:
   - Keep runbooks updated
   - Test documentation with new team members

5. **Encrypt Offsite Backups**:
```bash
# Encrypt before upload
rclone sync /var/backups/postgresql/ \
    ${RCLONE_REMOTE}/postgresql/ \
    --crypt-remote=encrypted:
```

## Next Steps

1. **[Review scaling strategy](./09-SCALING-STRATEGY.md)**
2. **[Check implementation phases](./10-IMPLEMENTATION-PHASES.md)**
