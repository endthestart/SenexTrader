# Senex Trader Deployment - Quick Reference

**Last Updated**: 2025-10-30
**Server**: your-domain.com

This is a quick reference for common deployment tasks. For detailed information, see [CURRENT-DEPLOYMENT-STATE.md](./CURRENT-DEPLOYMENT-STATE.md) and [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md).

## Quick Commands

### SSH Access

```bash
# SSH to server as root
ssh root@your-domain.com

# All service commands below assume you're already SSH'd in
```

### Check Service Status

```bash
# All services
systemctl --user -M senex@ list-units --type=service | grep -E "(web|celery|postgres|redis)"

# Specific service
systemctl --user -M senex@ status web.service

# Containers
sudo -u senex podman ps
```

### View Logs

```bash
# Web service (last 50 lines)
journalctl --user -M senex@ -u web.service -n 50 --no-pager

# Real-time logs
journalctl --user -M senex@ -u web.service -f

# Celery worker
journalctl --user -M senex@ -u celery-worker.service -n 50 --no-pager

# Nginx
tail -50 /var/log/nginx/error.log
```

### Restart Services

```bash
# Web only
systemctl --user -M senex@ restart web.service

# All app services
systemctl --user -M senex@ restart web.service celery-worker.service celery-beat.service

# Database/cache (be careful!)
systemctl --user -M senex@ restart postgres.service
systemctl --user -M senex@ restart redis.service

# Nginx
systemctl reload nginx
```

### Health Checks

```bash
# Web app (from server)
curl -I http://localhost:8000/health/

# External HTTPS
curl -I https://your-domain.com/health/

# PostgreSQL
sudo -u senex podman exec postgres pg_isready

# Redis
sudo -u senex podman exec redis redis-cli ping

# Database connection test
sudo -u senex podman exec postgres psql -U senex -d senex -c "SELECT version();"
```

### Backup & Restore

```bash
# Create manual backup
sudo -u senex podman exec postgres pg_dump -U senex senex | gzip > /opt/senex-trader/backups/manual-$(date +%Y-%m-%d-%H%M%S).sql.gz

# List backups
ls -lth /opt/senex-trader/backups/ | head

# Restore from backup (CAREFUL!)
# 1. Stop services
systemctl --user -M senex@ stop web.service celery-worker.service celery-beat.service

# 2. Restore
BACKUP="/opt/senex-trader/backups/pre-deploy-2025-10-30-022602.sql.gz"
gunzip < "$BACKUP" | sudo -u senex podman exec -i postgres psql -U senex -d senex

# 3. Restart services
systemctl --user -M senex@ start web.service celery-worker.service celery-beat.service
```

## Common Scenarios

### Deploy New Code Version

```bash
# 1. Create backup
sudo -u senex /opt/senex-trader/bin/postgres-backup.sh

# 2. Update .env with new IMAGE_TAG
sudo -u senex vim /opt/senex-trader/.config/containers/systemd/.env
# Change IMAGE_TAG=pre-deploy-YYYY-MM-DD-HHMMSS

# 3. Reload systemd and restart services
systemctl --user -M senex@ daemon-reload
systemctl --user -M senex@ restart web.service celery-worker.service celery-beat.service

# 4. Run migrations (if needed)
sudo -u senex podman exec web python manage.py migrate

# 5. Collect static files
sudo -u senex podman exec web python manage.py collectstatic --noinput

# 6. Verify
curl -I https://your-domain.com/health/
journalctl --user -M senex@ -u web.service -n 50
```

### Site is Down - Emergency Debug

```bash
# 1. Quick status check
systemctl status nginx
systemctl --user -M senex@ status web.service
curl -I http://localhost:8000/health/

# 2. Check dependencies
systemctl --user -M senex@ status postgres.service redis.service
sudo -u senex podman ps

# 3. Check disk space
df -h /opt/senex-trader/

# 4. Check recent logs
journalctl --user -M senex@ -u web.service -n 100 --no-pager
tail -100 /var/log/nginx/error.log

# 5. Emergency restart
systemctl --user -M senex@ restart postgres.service redis.service
sleep 5
systemctl --user -M senex@ restart web.service celery-worker.service celery-beat.service
systemctl reload nginx
```

### WebSocket Not Working

```bash
# 1. Check Redis Channels (DB 1)
sudo -u senex podman exec redis redis-cli -n 1 ping

# 2. Check web service logs
journalctl --user -M senex@ -u web.service | grep -i websocket

# 3. Check nginx WebSocket config
grep -A 10 "Upgrade" /etc/nginx/sites-enabled/your-domain.com

# 4. Test from server
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" http://localhost:8000/ws/market-data/

# 5. Restart services
systemctl --user -M senex@ restart redis.service web.service
systemctl reload nginx
```

### Celery Tasks Not Processing

```bash
# 1. Check celery worker
systemctl --user -M senex@ status celery-worker.service
journalctl --user -M senex@ -u celery-worker.service -n 50

# 2. Check Redis broker (DB 2)
sudo -u senex podman exec redis redis-cli -n 2 DBSIZE

# 3. Check from Django shell
sudo -u senex podman exec -it web python manage.py shell
>>> from celery import current_app
>>> current_app.control.inspect().active()
>>> exit()

# 4. Restart services
systemctl --user -M senex@ restart redis.service celery-worker.service celery-beat.service
```

### Database Connection Issues

```bash
# 1. Check PostgreSQL is running
systemctl --user -M senex@ status postgres.service
sudo -u senex podman exec postgres pg_isready

# 2. Test connection from web container
sudo -u senex podman exec web python manage.py dbshell

# 3. Check network connectivity
sudo -u senex podman exec web ping postgres

# 4. Check .env DATABASE_URL
sudo -u senex cat /opt/senex-trader/.config/containers/systemd/.env | grep DATABASE

# 5. Restart
systemctl --user -M senex@ restart postgres.service
sleep 10
systemctl --user -M senex@ restart web.service
```

## Important Paths

### Configuration

- **Quadlet files**: `/opt/senex-trader/.config/containers/systemd/`
- **Environment (.env)**: `/opt/senex-trader/.config/containers/systemd/.env`
- **Nginx config**: `/etc/nginx/sites-enabled/your-domain.com`
- **Systemd services**: `/opt/senex-trader/.config/systemd/user/`

### Data & Logs

- **PostgreSQL data**: `/opt/senex-trader/data/postgres/`
- **Redis data**: `/opt/senex-trader/data/redis/`
- **Static files**: `/opt/senex-trader/data/staticfiles/`
- **Backups**: `/opt/senex-trader/backups/`
- **Nginx logs**: `/var/log/nginx/`

### Scripts

- **Backup script**: `/opt/senex-trader/bin/postgres-backup.sh`
- **Watchdog**: `/opt/senex-trader/scripts/senex-watchdog.py`

## Service Dependencies

Services must start in this order:

1. `postgres.service` (database)
2. `redis.service` (cache/broker)
3. `web.service` (web app)
4. `celery-worker.service` (background tasks)
5. `celery-beat.service` (scheduler)

**Always restart in dependency order!**

## Environment Variables (.env)

Located at: `/opt/senex-trader/.config/containers/systemd/.env`

Key variables:
- `IMAGE_TAG` - Container image version to deploy
- `GITEA_REGISTRY` - Container registry URL
- `IMAGE_NAME` - Container image name
- `DB_NAME`, `DB_USER`, `DB_PASSWORD` - PostgreSQL credentials
- Plus all Django settings (DEBUG, SECRET_KEY, etc.)

## Container Registry

**Registry**: Configure in `.senextrader.json` (e.g., `your-registry.example.com/your-username/senex-trader`)

```bash
# Login to registry (if needed)
sudo -u senex podman login your-registry.example.com

# List local images
sudo -u senex podman images | grep senex-trader

# Pull specific tag
sudo -u senex podman pull your-registry.example.com/your-username/senex-trader:TAG

# Remove old images
sudo -u senex podman rmi IMAGE_ID
```

## Useful One-Liners

```bash
# Check all container health
sudo -u senex podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check disk usage
df -h /opt/senex-trader/ && sudo -u senex podman system df

# Count log errors in last hour
journalctl --user -M senex@ -u web.service --since "1 hour ago" | grep -i error | wc -l

# Check database size
sudo -u senex podman exec postgres psql -U senex -d senex -c "SELECT pg_size_pretty(pg_database_size('senex'));"

# Check Redis memory usage
sudo -u senex podman exec redis redis-cli INFO memory | grep used_memory_human

# Check active database connections
sudo -u senex podman exec postgres psql -U senex -d senex -c "SELECT count(*) FROM pg_stat_activity;"

# Find large files in backups
du -sh /opt/senex-trader/backups/* | sort -rh | head

# Check SSL certificate expiry
sudo certbot certificates | grep -A 2 your-domain.com
```

## Emergency Contacts

For production emergencies:
1. Check this quick reference first
2. Consult [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md)
3. Review [CURRENT-DEPLOYMENT-STATE.md](./CURRENT-DEPLOYMENT-STATE.md)
4. Check git history for recent changes

## Known Issues (Oct 2025)

1. **postgres-backup.service failing** - Manual backups working, automated timer needs debugging
2. **nginx http2 warnings** - Deprecated directive format, doesn't affect functionality
3. **Backup naming mismatch** - Script generates `postgres-*.sql.gz` but actual backups are `pre-deploy-*.sql.gz`

## Safety Reminders

- **Always create backup before deployment** - `sudo -u senex /opt/senex-trader/bin/postgres-backup.sh`
- **Test health after changes** - `curl -I https://your-domain.com/health/`
- **Check logs after restart** - `journalctl --user -M senex@ -u web.service -n 50`
- **Restart in dependency order** - postgres → redis → web → celery-worker → celery-beat
- **Never** `rm -rf` data directories - backups exist for a reason!

---

**For more details**: See [CURRENT-DEPLOYMENT-STATE.md](./CURRENT-DEPLOYMENT-STATE.md) and [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md)
