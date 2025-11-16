# Deployment Debugging Guide - Senex Trader

**Last Updated**: 2025-10-30
**For**: your-domain.com production deployment

This guide provides step-by-step debugging procedures for each service in the Senex Trader deployment.

## Table of Contents

1. [General Debugging Workflow](#general-debugging-workflow)
2. [Web Service (Daphne)](#web-service-daphne)
3. [Celery Worker](#celery-worker)
4. [Celery Beat](#celery-beat)
5. [PostgreSQL](#postgresql)
6. [Redis](#redis)
7. [Nginx](#nginx)
8. [Backup Service](#backup-service)
9. [Network Issues](#network-issues)
10. [Container Issues](#container-issues)
11. [Common Scenarios](#common-scenarios)

## General Debugging Workflow

### Step 1: Identify the Problem

```bash
# SSH to server
ssh root@your-domain.com

# Check all service statuses
systemctl --user -M senex@ list-units --type=service | grep -E "(web|celery|postgres|redis|backup)"

# Check container statuses
sudo -u senex podman ps -a

# Check system resources
df -h                    # Disk space
free -h                  # Memory
top                      # CPU usage
```

### Step 2: Check Logs

```bash
# Service logs (systemd)
journalctl --user -M senex@ -u SERVICE_NAME -n 100 --no-pager

# Container logs (podman)
sudo -u senex podman logs CONTAINER_NAME --tail 100

# Nginx logs
tail -100 /var/log/nginx/error.log
tail -100 /var/log/nginx/access.log
```

### Step 3: Test Dependencies

```bash
# Test database connection
sudo -u senex podman exec postgres pg_isready

# Test Redis
sudo -u senex podman exec redis redis-cli ping

# Test network connectivity
sudo -u senex podman network inspect senex-trader_senex_network
```

### Step 4: Review Configuration

```bash
# Check .env file
sudo -u senex cat /opt/senex-trader/.config/containers/systemd/.env

# Check quadlet definitions
ls -la /opt/senex-trader/.config/containers/systemd/

# Check nginx config
nginx -t
cat /etc/nginx/sites-enabled/your-domain.com
```

## Web Service (Daphne)

### Service Information

- **Service Name**: `web.service`
- **Container Name**: `web`
- **Port**: 8000
- **Image**: `gitea.andermic.net/endthestart/senex-trader:${IMAGE_TAG}`
- **Command**: `web` (runs Daphne ASGI server)

### Check Service Status

```bash
# Service status
systemctl --user -M senex@ status web.service

# Container status
sudo -u senex podman ps | grep web

# Port binding
sudo -u senex podman port web
# Expected: 8000/tcp -> 0.0.0.0:8000
```

### View Logs

```bash
# Real-time logs
journalctl --user -M senex@ -u web.service -f

# Last 100 lines
journalctl --user -M senex@ -u web.service -n 100 --no-pager

# Container logs
sudo -u senex podman logs web --tail 100
```

### Test Health

```bash
# Internal health check (from server)
curl -I http://localhost:8000/health/

# External health check
curl -I https://your-domain.com/health/

# WebSocket test
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: test" \
  http://localhost:8000/ws/market-data/
```

### Common Issues

#### Issue: Service fails to start

**Symptoms**: `systemctl status` shows "failed" or "activating"

**Debug:**
```bash
# Check logs for error message
journalctl --user -M senex@ -u web.service -n 50

# Check dependencies
systemctl --user -M senex@ status postgres.service redis.service

# Verify image exists
sudo -u senex podman images | grep senex-trader

# Check environment variables
sudo -u senex cat /opt/senex-trader/.config/containers/systemd/.env | grep -v PASSWORD
```

**Common Causes**:
- Database not ready (check postgres.service)
- Redis not ready (check redis.service)
- Missing/wrong IMAGE_TAG in .env
- Port 8000 already in use
- Missing staticfiles volume

#### Issue: Can't connect to database

**Symptoms**: Logs show "could not connect to server" or "connection refused"

**Debug:**
```bash
# Check PostgreSQL is running
systemctl --user -M senex@ status postgres.service

# Test connection from web container
sudo -u senex podman exec web python manage.py dbshell

# Check DATABASE_URL in .env
sudo -u senex cat /opt/senex-trader/.config/containers/systemd/.env | grep DATABASE

# Verify network connectivity
sudo -u senex podman exec web ping postgres
```

**Fix**:
```bash
# Restart postgres first
systemctl --user -M senex@ restart postgres.service

# Wait for it to be healthy
sudo -u senex podman exec postgres pg_isready

# Then restart web
systemctl --user -M senex@ restart web.service
```

#### Issue: Static files not loading

**Symptoms**: 404 errors for /static/ URLs, CSS/JS not loading

**Debug:**
```bash
# Check staticfiles volume mount
sudo -u senex podman inspect web | grep -A 5 Mounts

# Check directory exists and has files
ls -la /opt/senex-trader/data/staticfiles/

# Check nginx static file config
grep -A 5 "location /static" /etc/nginx/sites-enabled/your-domain.com

# Check nginx can access the directory
sudo -u www-data ls /opt/senex-trader/data/staticfiles/
```

**Fix**:
```bash
# Collect static files
sudo -u senex podman exec web python manage.py collectstatic --noinput

# Fix permissions
sudo chown -R senex:www-data /opt/senex-trader/data/staticfiles/
sudo chmod -R 755 /opt/senex-trader/data/staticfiles/

# Restart nginx
systemctl restart nginx
```

#### Issue: WebSocket connections failing

**Symptoms**: Real-time updates not working, "websocket closed" in browser console

**Debug:**
```bash
# Check Channels layer (Redis DB 1)
sudo -u senex podman exec redis redis-cli -n 1 ping

# Check nginx WebSocket config
grep -A 10 "Upgrade" /etc/nginx/sites-enabled/your-domain.com

# Test WebSocket from server
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  http://localhost:8000/ws/market-data/

# Check logs for WebSocket errors
journalctl --user -M senex@ -u web.service | grep -i websocket
```

**Fix**:
```bash
# Restart Redis
systemctl --user -M senex@ restart redis.service

# Restart web service
systemctl --user -M senex@ restart web.service

# If nginx is the issue, reload nginx
systemctl reload nginx
```

### Restart Procedure

```bash
# Graceful restart
systemctl --user -M senex@ restart web.service

# Check it came back up
systemctl --user -M senex@ status web.service

# Verify health
curl -I http://localhost:8000/health/
```

## Celery Worker

### Service Information

- **Service Name**: `celery-worker.service`
- **Container Name**: `celery_worker`
- **Image**: Same as web
- **Command**: `celery-worker`

### Check Service Status

```bash
# Service status
systemctl --user -M senex@ status celery-worker.service

# Container status
sudo -u senex podman ps | grep celery_worker
```

### View Logs

```bash
# Real-time logs
journalctl --user -M senex@ -u celery-worker.service -f

# Last 100 lines
journalctl --user -M senex@ -u celery-worker.service -n 100 --no-pager
```

### Test Celery

```bash
# Check Celery can connect to broker (Redis DB 2)
sudo -u senex podman exec redis redis-cli -n 2 ping

# Inspect Celery from Django shell
sudo -u senex podman exec -it web python manage.py shell
>>> from celery import current_app
>>> current_app.control.inspect().active()
>>> current_app.control.inspect().stats()
```

### Common Issues

#### Issue: Worker not processing tasks

**Symptoms**: Tasks stuck in "pending", no activity in logs

**Debug:**
```bash
# Check worker is running
systemctl --user -M senex@ status celery-worker.service

# Check Redis broker connection
sudo -u senex podman exec redis redis-cli -n 2 DBSIZE
sudo -u senex podman exec redis redis-cli -n 2 KEYS '*'

# Check for task queue
sudo -u senex podman exec web python manage.py shell
>>> from trading.tasks import test_task
>>> result = test_task.delay()
>>> result.status
```

**Fix**:
```bash
# Restart worker
systemctl --user -M senex@ restart celery-worker.service

# If Redis is the issue
systemctl --user -M senex@ restart redis.service
systemctl --user -M senex@ restart celery-worker.service
```

#### Issue: Tasks failing with errors

**Debug:**
```bash
# Check worker logs for exceptions
journalctl --user -M senex@ -u celery-worker.service | grep -i error

# Check task results in Redis (DB 3)
sudo -u senex podman exec redis redis-cli -n 3 KEYS '*'

# Check from Django shell
sudo -u senex podman exec -it web python manage.py shell
>>> from celery.result import AsyncResult
>>> result = AsyncResult('task-id-here')
>>> result.traceback
```

## Celery Beat

### Service Information

- **Service Name**: `celery-beat.service`
- **Container Name**: `celery_beat`
- **Image**: Same as web
- **Command**: `celery-beat` (periodic task scheduler)

### Check Service Status

```bash
# Service status
systemctl --user -M senex@ status celery-beat.service

# Container status
sudo -u senex podman ps | grep celery_beat
```

### View Logs

```bash
# Real-time logs
journalctl --user -M senex@ -u celery-beat.service -f

# Look for "Scheduler: Sending due task"
journalctl --user -M senex@ -u celery-beat.service | grep -i "sending due"
```

### Common Issues

#### Issue: Scheduled tasks not running

**Debug:**
```bash
# Check beat is running
systemctl --user -M senex@ status celery-beat.service

# Check scheduled tasks in logs
journalctl --user -M senex@ -u celery-beat.service -n 200 | grep "Scheduler"

# Check periodic task configuration
sudo -u senex podman exec web python manage.py shell
>>> from django_celery_beat.models import PeriodicTask
>>> PeriodicTask.objects.all()
```

**Fix**:
```bash
# Restart beat scheduler
systemctl --user -M senex@ restart celery-beat.service

# Ensure worker is also running
systemctl --user -M senex@ restart celery-worker.service
```

## PostgreSQL

### Service Information

- **Service Name**: `postgres.service`
- **Container Name**: `postgres`
- **Image**: `docker.io/library/postgres:15-alpine`
- **Port**: 5432 (internal only)
- **Database**: `senex`
- **User**: `senex`

### Check Service Status

```bash
# Service status
systemctl --user -M senex@ status postgres.service

# Container status
sudo -u senex podman ps | grep postgres

# Database health
sudo -u senex podman exec postgres pg_isready
```

### View Logs

```bash
# Service logs
journalctl --user -M senex@ -u postgres.service -n 100

# Container logs
sudo -u senex podman logs postgres --tail 100
```

### Connect to Database

```bash
# psql shell
sudo -u senex podman exec -it postgres psql -U senex -d senex

# Run SQL query
sudo -u senex podman exec postgres psql -U senex -d senex -c "SELECT version();"

# List databases
sudo -u senex podman exec postgres psql -U senex -c "\l"

# List tables
sudo -u senex podman exec postgres psql -U senex -d senex -c "\dt"
```

### Common Issues

#### Issue: Database not starting

**Debug:**
```bash
# Check logs for errors
journalctl --user -M senex@ -u postgres.service -n 50

# Check data directory permissions
ls -ld /opt/senex-trader/data/postgres/

# Check disk space
df -h /opt/senex-trader/

# Check if port is already in use
sudo -u senex podman exec postgres netstat -ln | grep 5432
```

**Fix**:
```bash
# If permission issues (should be owned by subuid mapping)
sudo chown -R senex:senex /opt/senex-trader/data/postgres/

# Restart service
systemctl --user -M senex@ restart postgres.service
```

#### Issue: Connection refused

**Debug:**
```bash
# Check PostgreSQL is listening
sudo -u senex podman exec postgres netstat -ln | grep 5432

# Test connection from another container
sudo -u senex podman exec web nc -zv postgres 5432

# Check network connectivity
sudo -u senex podman network inspect senex-trader_senex_network
```

#### Issue: Database corruption

**Symptoms**: "invalid page header", "corrupted" messages in logs

**Recovery:**
```bash
# STOP - This is serious. Create backup first if possible
sudo -u senex podman exec postgres pg_dump -U senex senex > /tmp/emergency-backup.sql

# Check for recent backups
ls -lth /opt/senex-trader/backups/ | head

# Restore from backup (see Backup Service section)
```

### Performance Checks

```bash
# Check active connections
sudo -u senex podman exec postgres psql -U senex -d senex -c \
  "SELECT count(*) FROM pg_stat_activity;"

# Check slow queries
sudo -u senex podman exec postgres psql -U senex -d senex -c \
  "SELECT query, query_start, state FROM pg_stat_activity WHERE state != 'idle';"

# Check database size
sudo -u senex podman exec postgres psql -U senex -d senex -c \
  "SELECT pg_size_pretty(pg_database_size('senex'));"
```

## Redis

### Service Information

- **Service Name**: `redis.service`
- **Container Name**: `redis`
- **Image**: `docker.io/library/redis:7-alpine`
- **Port**: 6379 (internal only)
- **Max Memory**: 512MB (with LRU eviction)

### Check Service Status

```bash
# Service status
systemctl --user -M senex@ status redis.service

# Container status
sudo -u senex podman ps | grep redis

# Redis health
sudo -u senex podman exec redis redis-cli ping
```

### View Logs

```bash
# Service logs
journalctl --user -M senex@ -u redis.service -n 100

# Container logs
sudo -u senex podman logs redis --tail 100
```

### Redis CLI

```bash
# Connect to Redis
sudo -u senex podman exec -it redis redis-cli

# Check info
sudo -u senex podman exec redis redis-cli INFO

# Check memory usage
sudo -u senex podman exec redis redis-cli INFO memory

# Check keyspace
sudo -u senex podman exec redis redis-cli INFO keyspace
```

### Database Usage

```bash
# Check Django cache (DB 0)
sudo -u senex podman exec redis redis-cli -n 0 DBSIZE

# Check Channels (DB 1)
sudo -u senex podman exec redis redis-cli -n 1 DBSIZE

# Check Celery broker (DB 2)
sudo -u senex podman exec redis redis-cli -n 2 DBSIZE

# Check Celery results (DB 3)
sudo -u senex podman exec redis redis-cli -n 3 DBSIZE
```

### Common Issues

#### Issue: Out of memory

**Symptoms**: "OOM command not allowed", evictions in logs

**Debug:**
```bash
# Check memory usage
sudo -u senex podman exec redis redis-cli INFO memory | grep used_memory_human

# Check eviction policy
sudo -u senex podman exec redis redis-cli CONFIG GET maxmemory-policy
# Should be: allkeys-lru

# Check max memory
sudo -u senex podman exec redis redis-cli CONFIG GET maxmemory
# Should be: 536870912 (512MB)
```

**Fix**:
```bash
# Flush least-used data (careful!)
sudo -u senex podman exec redis redis-cli FLUSHDB

# Or increase maxmemory (edit quadlet file)
sudo -u senex vim /opt/senex-trader/.config/containers/systemd/redis.container
# Change: --maxmemory 1024mb

# Restart Redis
systemctl --user -M senex@ daemon-reload
systemctl --user -M senex@ restart redis.service
```

#### Issue: High CPU usage

**Debug:**
```bash
# Check slow log
sudo -u senex podman exec redis redis-cli SLOWLOG GET 10

# Check connected clients
sudo -u senex podman exec redis redis-cli CLIENT LIST
```

## Nginx

### Service Information

- **Service Type**: System service (not containerized)
- **Service Name**: `nginx.service`
- **Ports**: 80 (HTTP), 443 (HTTPS)
- **Config**: `/etc/nginx/sites-enabled/your-domain.com`

### Check Service Status

```bash
# Service status
systemctl status nginx

# Test configuration
nginx -t

# Check process
ps aux | grep nginx
```

### View Logs

```bash
# Access log (real-time)
tail -f /var/log/nginx/access.log

# Error log (real-time)
tail -f /var/log/nginx/error.log

# Last 100 errors
tail -100 /var/log/nginx/error.log

# Filter for specific error
grep "502 Bad Gateway" /var/log/nginx/error.log
```

### Common Issues

#### Issue: 502 Bad Gateway

**Symptoms**: Users see 502 error, nginx error log shows "connect() failed"

**Debug:**
```bash
# Check if backend is running
curl -I http://localhost:8000/health/

# Check nginx can reach backend
sudo -u www-data curl -I http://localhost:8000/health/

# Check upstream in nginx config
grep upstream /etc/nginx/sites-enabled/your-domain.com
# Should be: server 127.0.0.1:8000;

# Check if web service is listening on 8000
netstat -tlnp | grep 8000
```

**Fix**:
```bash
# Restart web service
systemctl --user -M senex@ restart web.service

# Reload nginx
systemctl reload nginx
```

#### Issue: SSL certificate errors

**Debug:**
```bash
# Check certificate expiry
sudo certbot certificates

# Test SSL
curl -vI https://your-domain.com 2>&1 | grep -i "expire\|valid"

# Check certificate files exist
ls -l /etc/letsencrypt/live/your-domain.com/
```

**Fix (renew certificate):**
```bash
# Renew certificate
sudo certbot renew

# If that fails, force renewal
sudo certbot renew --force-renewal

# Reload nginx
systemctl reload nginx
```

#### Issue: WebSocket upgrade failing

**Debug:**
```bash
# Check WebSocket config in nginx
grep -A 5 "Upgrade" /etc/nginx/sites-enabled/your-domain.com

# Test WebSocket upgrade
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: test" \
  https://your-domain.com/ws/market-data/
```

### Reload vs Restart

```bash
# Graceful reload (no downtime, recommended)
nginx -t && systemctl reload nginx

# Full restart (brief downtime)
systemctl restart nginx
```

## Backup Service

### Service Information

- **Service Name**: `postgres-backup.service`
- **Timer**: `postgres-backup.timer`
- **Schedule**: Daily at 02:00 UTC
- **Script**: `/opt/senex-trader/bin/postgres-backup.sh`
- **Backup Location**: `/opt/senex-trader/backups/`

### Check Service Status

```bash
# Timer status
systemctl --user -M senex@ status postgres-backup.timer

# Service status (after last run)
systemctl --user -M senex@ status postgres-backup.service

# Last run time
systemctl --user -M senex@ list-timers | grep postgres-backup
```

### View Logs

```bash
# Service logs
journalctl --user -M senex@ -u postgres-backup.service -n 50

# All backup attempts
journalctl --user -M senex@ -u postgres-backup.service --since "7 days ago"
```

### Manual Backup

```bash
# Run backup script manually
sudo -u senex /opt/senex-trader/bin/postgres-backup.sh

# Or trigger service
systemctl --user -M senex@ start postgres-backup.service

# Check result
ls -lth /opt/senex-trader/backups/ | head
```

### Common Issues

#### Issue: Backup service failing (CURRENT ISSUE)

**Status**: ⚠️ Service is currently failing as of Oct 30, 2025

**Debug:**
```bash
# Check service failure reason
systemctl --user -M senex@ status postgres-backup.service

# Check logs for error
journalctl --user -M senex@ -u postgres-backup.service -n 100

# Test backup script manually
sudo -u senex bash -x /opt/senex-trader/bin/postgres-backup.sh

# Check script can access podman
sudo -u senex podman ps | grep postgres

# Check postgres container is healthy
sudo -u senex podman exec postgres pg_isready
```

**Potential Causes**:
1. Permission issues (script can't write to backup directory)
2. Podman socket not accessible from systemd service
3. PostgreSQL not ready when backup runs
4. Disk space issues

**Fix (permission issue):**
```bash
# Ensure backup directory is owned by senex
sudo chown senex:senex /opt/senex-trader/backups/
sudo chmod 755 /opt/senex-trader/backups/

# Retry
systemctl --user -M senex@ start postgres-backup.service
```

**Fix (podman socket issue):**
```bash
# Check if DBUS_SESSION_BUS_ADDRESS is set in service
systemctl --user -M senex@ cat postgres-backup.service

# May need to add Environment=DBUS_SESSION_BUS_ADDRESS in service file
```

### Restore from Backup

```bash
# List available backups
ls -lh /opt/senex-trader/backups/

# Stop web services (to prevent writes)
systemctl --user -M senex@ stop web.service celery-worker.service celery-beat.service

# Restore backup
BACKUP_FILE="/opt/senex-trader/backups/pre-deploy-2025-10-30-022602.sql.gz"
gunzip < "$BACKUP_FILE" | sudo -u senex podman exec -i postgres psql -U senex -d senex

# Restart services
systemctl --user -M senex@ start postgres.service redis.service
systemctl --user -M senex@ start web.service celery-worker.service celery-beat.service

# Verify
curl -I http://localhost:8000/health/
```

## Network Issues

### Check Podman Network

```bash
# List networks
sudo -u senex podman network ls

# Inspect senex network
sudo -u senex podman network inspect senex-trader_senex_network

# Check DNS resolution between containers
sudo -u senex podman exec web ping postgres
sudo -u senex podman exec web ping redis
```

### Common Issues

#### Issue: Containers can't communicate

**Debug:**
```bash
# Check all containers are on same network
sudo -u senex podman inspect web | grep -i network
sudo -u senex podman inspect postgres | grep -i network
sudo -u senex podman inspect redis | grep -i network

# Test connectivity
sudo -u senex podman exec web nc -zv postgres 5432
sudo -u senex podman exec web nc -zv redis 6379
```

**Fix:**
```bash
# Recreate network (requires stopping containers)
systemctl --user -M senex@ stop web.service celery-worker.service celery-beat.service
sudo -u senex podman network rm senex-trader_senex_network
systemctl --user -M senex@ daemon-reload
systemctl --user -M senex@ start postgres.service redis.service
systemctl --user -M senex@ start web.service celery-worker.service celery-beat.service
```

## Container Issues

### Check Container Runtime

```bash
# Podman version
sudo -u senex podman version

# Podman info
sudo -u senex podman info

# Check storage
sudo -u senex podman system df
```

### Common Issues

#### Issue: "No space left on device"

**Debug:**
```bash
# Check disk space
df -h /opt/senex-trader/
df -h /var/lib/containers/

# Check podman storage usage
sudo -u senex podman system df
```

**Fix:**
```bash
# Clean up unused containers/images
sudo -u senex podman system prune -a

# Remove old images
sudo -u senex podman images
sudo -u senex podman rmi IMAGE_ID

# Clean old backups
find /opt/senex-trader/backups/ -name "*.sql.gz" -mtime +7 -delete
```

#### Issue: Image pull fails

**Debug:**
```bash
# Check registry connectivity
ping gitea.andermic.net

# Check credentials
sudo -u senex podman login gitea.andermic.net

# Try manual pull
sudo -u senex podman pull gitea.andermic.net/endthestart/senex-trader:latest
```

## Common Scenarios

### Scenario: Site is completely down

```bash
# 1. Check nginx
systemctl status nginx
curl -I http://localhost:8000/health/

# 2. Check web service
systemctl --user -M senex@ status web.service
journalctl --user -M senex@ -u web.service -n 50

# 3. Check dependencies
systemctl --user -M senex@ status postgres.service redis.service

# 4. Check disk space
df -h

# 5. Restart services
systemctl --user -M senex@ restart postgres.service
systemctl --user -M senex@ restart redis.service
systemctl --user -M senex@ restart web.service
systemctl reload nginx
```

### Scenario: Real-time updates not working

```bash
# 1. Check WebSocket connection in browser console
# Look for "WebSocket connected" or errors

# 2. Check Redis Channels (DB 1)
sudo -u senex podman exec redis redis-cli -n 1 ping

# 3. Check web service logs for WebSocket errors
journalctl --user -M senex@ -u web.service | grep -i websocket

# 4. Check nginx WebSocket config
grep -A 10 "Upgrade" /etc/nginx/sites-enabled/your-domain.com

# 5. Restart services
systemctl --user -M senex@ restart redis.service
systemctl --user -M senex@ restart web.service
systemctl reload nginx
```

### Scenario: Background tasks not processing

```bash
# 1. Check celery worker
systemctl --user -M senex@ status celery-worker.service
journalctl --user -M senex@ -u celery-worker.service -n 50

# 2. Check celery beat
systemctl --user -M senex@ status celery-beat.service

# 3. Check Redis broker (DB 2)
sudo -u senex podman exec redis redis-cli -n 2 DBSIZE

# 4. Test task submission
sudo -u senex podman exec web python manage.py shell
>>> from trading.tasks import test_task
>>> test_task.delay()

# 5. Restart celery services
systemctl --user -M senex@ restart redis.service
systemctl --user -M senex@ restart celery-worker.service
systemctl --user -M senex@ restart celery-beat.service
```

### Scenario: After deploying new code

```bash
# 1. Create backup
sudo -u senex /opt/senex-trader/bin/postgres-backup.sh

# 2. Update .env with new IMAGE_TAG
sudo -u senex vim /opt/senex-trader/.config/containers/systemd/.env

# 3. Reload systemd
systemctl --user -M senex@ daemon-reload

# 4. Restart services
systemctl --user -M senex@ restart web.service
systemctl --user -M senex@ restart celery-worker.service
systemctl --user -M senex@ restart celery-beat.service

# 5. Run migrations (if needed)
sudo -u senex podman exec web python manage.py migrate

# 6. Collect static files
sudo -u senex podman exec web python manage.py collectstatic --noinput

# 7. Test
curl -I https://your-domain.com/health/

# 8. Check logs
journalctl --user -M senex@ -u web.service -n 50
```

## Emergency Procedures

### Complete Service Restart

```bash
# Stop all app services
systemctl --user -M senex@ stop web.service
systemctl --user -M senex@ stop celery-worker.service
systemctl --user -M senex@ stop celery-beat.service

# Restart data services
systemctl --user -M senex@ restart postgres.service
systemctl --user -M senex@ restart redis.service

# Wait for health
sleep 10
sudo -u senex podman exec postgres pg_isready
sudo -u senex podman exec redis redis-cli ping

# Start app services
systemctl --user -M senex@ start web.service
systemctl --user -M senex@ start celery-worker.service
systemctl --user -M senex@ start celery-beat.service

# Reload nginx
systemctl reload nginx

# Verify
curl -I https://your-domain.com/health/
```

### Rollback to Previous Version

```bash
# 1. Find previous working IMAGE_TAG
ls -lt /opt/senex-trader/backups/
# Backups are named with timestamps matching deployments

# 2. Update .env
sudo -u senex vim /opt/senex-trader/.config/containers/systemd/.env
# Change IMAGE_TAG to previous version

# 3. Restore database (if needed)
BACKUP="/opt/senex-trader/backups/pre-deploy-YYYY-MM-DD-HHMMSS.sql.gz"
systemctl --user -M senex@ stop web.service celery-worker.service celery-beat.service
gunzip < "$BACKUP" | sudo -u senex podman exec -i postgres psql -U senex -d senex

# 4. Restart services
systemctl --user -M senex@ restart web.service celery-worker.service celery-beat.service

# 5. Verify
curl -I https://your-domain.com/health/
```

## Additional Resources

- **Current Deployment State**: [CURRENT-DEPLOYMENT-STATE.md](./CURRENT-DEPLOYMENT-STATE.md)
- **Deployment Overview**: [00-OVERVIEW.md](./00-OVERVIEW.md)
- **Quadlet Documentation**: https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html
- **Systemd Documentation**: https://www.freedesktop.org/software/systemd/man/

---

**Last Updated**: 2025-10-30
**Maintainer**: Infrastructure Team
**Next Review**: 2025-11-30
