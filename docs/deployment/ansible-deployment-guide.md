# Senex Trader Deployment Guide

## Overview

This directory contains **Ansible playbooks** for deploying Senex Trader to **staging** and **production** environments using **Podman Quadlet**.

**Deployment Method:** Ansible + Podman 5.x + Quadlet (systemd-native containers)
**Based on:** options_strategy_trader reference application
**Container Image:** `gitea.andermic.net/endthestart/senex-trader:v0.1.16`

**What is Quadlet?** Podman Quadlet is systemd-native container management (Podman 4.4+). It provides reliable auto-restart and lifecycle management via systemd instead of podman-compose.

## Architecture

### Services (5 Containers)
1. **PostgreSQL 15** - Database (postgres:15-alpine, matches production)
2. **Redis 7** - Cache/Broker (redis:7-alpine, matches production)
3. **Django/Daphne** - ASGI web server with WebSocket support
4. **Celery Worker** - Background task processing
5. **Celery Beat** - Scheduled task scheduler

### Environments

| Environment | Host | User | Podman | SSL | Access |
|-------------|------|------|--------|-----|--------|
| **Staging** | 10.0.0.100 | root (rootful) | 5.x | Yes (external nginx) | https://your-app.example.com |
| **Production** | your-domain.com | senex (rootless) | 5.x | Yes (local nginx) | https://your-domain.com |

### Version Alignment

**Why Debian 13 (Trixie)?**
- Debian 13 ships with Podman 5.x which includes native Quadlet support
- Podman 4.x (Debian 12) has known reliability issues with podman-compose
- Both staging and production now run Debian 13 for consistency

**Why PostgreSQL 15 and Redis 7?**
- Production deployment runs on servers with these versions
- Using matching versions ensures staging accurately represents production

## Prerequisites

### On Control Machine (Your Laptop)
- Ansible 2.10+ installed
- SSH access to target servers
- Access to Gitea registry (gitea.andermic.net)

### On Target Servers
- Ubuntu/Debian Linux
- SSH access configured
- Sudo privileges
- **Previous installations cleaned up manually**

## Quick Start

### 1. Generate Secrets

Generate required secrets on your control machine:

```bash
# Django secret key
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# Field encryption key (Fernet)
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

# Database password
openssl rand -base64 32

# Note these values - you'll need them for vault files
```

### 2. Create Vault Files

Create encrypted vault files for each environment:

```bash
cd deployment/ansible

# Create staging vault
cp inventory/staging-vault.yml.example inventory/staging-vault.yml
# Edit staging-vault.yml and fill in real values
ansible-vault encrypt inventory/staging-vault.yml

# Create production vault
cp inventory/production-vault.yml.example inventory/production-vault.yml
# Edit production-vault.yml and fill in real values
ansible-vault encrypt inventory/production-vault.yml
```

**Vault Password:** Store your vault password securely. You'll need it for every deployment.

### 3. Verify Inventory

Check that servers are accessible:

```bash
cd deployment/ansible

# Test staging connectivity
ansible staging -i inventory/hosts.yml -m ping --ask-vault-pass

# Test production connectivity
ansible production -i inventory/hosts.yml -m ping --ask-vault-pass
```

### 4. Deploy to Staging

```bash
cd deployment/ansible

ansible-playbook deploy.yml --limit staging --ask-vault-pass
```

**What this does:**
1. Updates system packages (upgrades to Debian 13 if needed)
2. Creates application user and directories
3. Installs Podman 5.x and dependencies
4. Configures UFW firewall (including Podman internal network)
5. Templates Quadlet .container files
6. Creates systemd drop-ins for environment variable substitution
7. Creates .env from vault variables
8. Logs into Gitea registry
9. Pulls container image (v0.1.16)
10. Generates systemd services via Quadlet
11. Starts all 5 services via systemd
12. Verifies health endpoint

**Verification:**
```bash
# Check health (direct access)
curl http://10.0.0.100:8000/health/

# Check health (via nginx proxy)
curl https://your-app.example.com/health/

# Expected response:
{"status": "healthy"}
```

**Post-Deployment Verification:**
```bash
# Check systemd services
ssh root@10.0.0.100
systemctl status web.service postgres.service redis.service

# Check containers
podman ps

# View logs
journalctl -u web.service -n 50
```

**Firewall Note:** Staging requires UFW route rule for external nginx proxy (10.0.0.209). This is automatically configured by Ansible for staging only.

### 5. Deploy to Production

**IMPORTANT:** Production deployment includes SSL certificate generation via Let's Encrypt.

```bash
cd deployment/ansible

ansible-playbook deploy.yml --limit production --ask-vault-pass
```

**Additional production steps:**
1. Installs Nginx as reverse proxy
2. Configures Nginx with proxy settings
3. Obtains SSL certificate via Certbot
4. Configures HTTPS redirect

**Verification:**
```bash
# Check health
curl https://your-domain.com/health/

# Expected response:
{"status": "healthy"}
```

## File Structure

```
deployment/
├── README.md                            # This file
├── ENVIRONMENT_DIFFERENCES.md           # Staging vs production differences
├── quadlet/                             # Source Quadlet files (not templated)
│   ├── celery-beat.container
│   ├── celery-worker.container
│   ├── postgres.container
│   ├── redis.container
│   ├── web.container
│   └── senex-network.network
└── ansible/
    ├── ansible.cfg                      # Ansible configuration
    ├── deploy.yml                       # Main deployment playbook (Quadlet-based)
    ├── inventory/
    │   ├── hosts.yml                    # Server inventory
    │   ├── staging-vault.yml            # Staging secrets (encrypted)
    │   ├── staging-vault.yml.example    # Staging template
    │   ├── production-vault.yml         # Production secrets (encrypted)
    │   └── production-vault.yml.example # Production template
    └── templates/
        ├── env.j2                       # Environment file template
        ├── nginx-site.j2                # Nginx configuration template
        ├── nginx-site-ssl.j2            # Nginx SSL configuration template
        └── quadlet/                     # Quadlet templates (environment-aware)
            ├── celery-beat.container.j2
            ├── celery-worker.container.j2
            ├── postgres.container.j2
            ├── redis.container.j2
            └── web.container.j2
```

## Common Operations

### Update Application

To deploy a new version:

1. **Build and push new image:**
   ```bash
   cd /path/to/senextrader
   python build.py --tag v0.2.0
   ```

2. **Update inventory:**
   ```bash
   # Edit deployment/ansible/inventory/hosts.yml
   # Change image_tag: v0.2.0
   ```

3. **Deploy:**
   ```bash
   cd deployment/ansible
   ansible-playbook deploy.yml --limit production --ask-vault-pass
   ```

### View Logs

**Quadlet uses systemd for logging (journalctl)**

```bash
# SSH to server
ssh root@your-domain.com  # staging: ssh root@10.0.0.100

# View Django logs
journalctl -u web.service -n 100

# View Celery worker logs
journalctl -u celery-worker.service -n 100

# View Celery beat logs
journalctl -u celery-beat.service -n 100

# View PostgreSQL logs
journalctl -u postgres.service -n 100

# View Redis logs
journalctl -u redis.service -n 100

# Follow logs in real-time
journalctl -u web.service -f

# View all service logs together
journalctl -u web.service -u celery-worker.service -u postgres.service -f
```

**Alternative: Direct container logs**
```bash
# Podman container logs still work
podman logs web
podman logs -f web
```

### Restart Services

**Quadlet services are managed via systemd**

```bash
# SSH to server
ssh root@your-domain.com

# For rootless (production):
ssh senex@your-domain.com
systemctl --user restart web.service
systemctl --user restart celery-worker.service celery-beat.service

# For rootful (staging):
ssh root@10.0.0.100
systemctl restart web.service
systemctl restart celery-worker.service celery-beat.service

# Restart all services
systemctl restart postgres.service redis.service web.service celery-worker.service celery-beat.service

# Restart Django and Celery only
systemctl restart web.service celery-worker.service celery-beat.service
```

**Alternative: Direct Podman commands** (bypasses systemd)
```bash
podman restart web
podman restart celery_worker celery_beat
```

### Check Service Status

**Quadlet services show systemd status**

```bash
# SSH to server
ssh root@your-domain.com

# For rootless (production):
systemctl --user status web.service
systemctl --user status postgres.service redis.service celery-worker.service celery-beat.service

# For rootful (staging):
systemctl status web.service
systemctl status postgres.service redis.service

# List all containers
podman ps

# Check container health
podman ps --format "{{.Names}}: {{.Status}}"

# Check specific service
podman inspect web | grep -i status
```

### Access Database

**Container names are simplified (no senextrader_ prefix)**

```bash
# SSH to server
ssh root@your-domain.com

# PostgreSQL shell
podman exec -it postgres psql -U senex_user -d senextrader

# Run Django migrations
podman exec -it web python manage.py migrate

# Create superuser
podman exec -it web python manage.py createsuperuser

# Django shell
podman exec -it web python manage.py shell
```

### Run Management Commands

**IMPORTANT:** Management commands automatically use production settings when run inside containers.

The `manage.py` script reads the `DJANGO_SETTINGS_MODULE` environment variable set in .env, ensuring production commands always use the correct settings (PostgreSQL, not SQLite).

```bash
# SSH to server
ssh root@your-domain.com

# Bootstrap historical data (90 days for core symbols)
podman exec -it web python manage.py preload_historical --days 90

# Load historical data for specific symbols
podman exec -it web python manage.py preload_historical --symbols SPY QQQ --days 90

# Load 10 years of data for backtesting
podman exec -it web python manage.py preload_historical --days 3650

# Load current market metrics (IV Rank, etc.)
podman exec -it web python manage.py preload_market_metrics --symbols SPY QQQ

# Backfill user order history
podman exec -it web python manage.py backfill_order_history --days-back 60

# Daily data update (normally runs via Celery Beat)
podman exec -it web python manage.py daily_data_update
```

**How It Works:**
1. .env file sets `DJANGO_SETTINGS_MODULE=senextrader.settings.production`
2. Quadlet passes .env to container via `EnvironmentFile=`
3. manage.py uses the settings module from environment
4. Commands automatically connect to PostgreSQL, not SQLite

**Verification:**
```bash
# Check which settings are being used (should show 'production')
podman exec -it web python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])"
# Output: django.db.backends.postgresql

# Check historical data was loaded
podman exec -it web python manage.py shell -c "from trading.models import HistoricalPrice; print(f'QQQ: {HistoricalPrice.objects.filter(symbol=\"QQQ\").count()} days')"
```

### Database Backup and Restore

**Automated Daily Backups**: The deployment automatically sets up daily PostgreSQL backups at 2 AM via systemd timer.

**Backup Locations**:
- `/opt/senex-trader/backups/postgres-YYYY-MM-DD-HHMMSS.sql.gz` (daily automated)
- `/opt/senex-trader/backups/pre-deploy-YYYY-MM-DD-HHMMSS.sql.gz` (pre-deployment)

**Configuration** (in `hosts.yml`):
```yaml
backup_enabled: true           # Enable/disable backups
backup_retention_days: 7       # Days to keep backups
backup_compress: true          # gzip compression
backup_schedule: "02:00"       # Daily run time (2 AM)
```

#### Manual Backup

```bash
# SSH to server
ssh root@your-domain.com  # or ssh senex@your-domain.com

# Manual backup (compressed)
podman exec postgres pg_dump -U senex_user senextrader | gzip > /opt/senex-trader/backups/manual-$(date +%Y-%m-%d-%H%M%S).sql.gz

# Manual backup (uncompressed)
podman exec postgres pg_dump -U senex_user senextrader > /opt/senex-trader/backups/manual-$(date +%Y-%m-%d-%H%M%S).sql

# Verify backup
ls -lh /opt/senex-trader/backups/
```

#### Restore from Backup

```bash
# SSH to server
ssh root@your-domain.com

# List available backups
ls -lh /opt/senex-trader/backups/

# Restore from compressed backup
gunzip -c /opt/senex-trader/backups/postgres-2025-10-15-020000.sql.gz | \
  podman exec -i postgres psql -U senex_user -d senextrader

# Restore from uncompressed backup
cat /opt/senex-trader/backups/pre-deploy-2025-10-15-120000.sql | \
  podman exec -i postgres psql -U senex_user -d senextrader

# Restore from specific backup (drops existing database first)
gunzip -c /opt/senex-trader/backups/postgres-2025-10-15-020000.sql.gz | \
  podman exec -i postgres psql -U senex_user -d postgres -c "DROP DATABASE IF EXISTS senextrader; CREATE DATABASE senextrader;" && \
  gunzip -c /opt/senex-trader/backups/postgres-2025-10-15-020000.sql.gz | \
  podman exec -i postgres psql -U senex_user -d senextrader
```

#### Monitor Automated Backups

```bash
# Check backup timer status
# Rootful (staging):
systemctl status postgres-backup.timer
systemctl list-timers postgres-backup.timer

# Rootless (production):
systemctl --user status postgres-backup.timer
systemctl --user list-timers postgres-backup.timer

# View backup service logs
# Rootful:
journalctl -u postgres-backup.service -n 50

# Rootless:
journalctl --user -u postgres-backup.service -n 50

# Manually trigger backup (for testing)
# Rootful:
systemctl start postgres-backup.service

# Rootless:
systemctl --user start postgres-backup.service
```

#### Backup Retention

Backups are automatically rotated. Old backups older than `backup_retention_days` (default 7) are deleted when new backups run.

```bash
# List all backups with age
find /opt/senex-trader/backups -name "postgres-*.sql.gz" -type f -exec ls -lh {} \;

# Manually delete old backups (30+ days)
find /opt/senex-trader/backups -name "postgres-*.sql.gz" -type f -mtime +30 -delete
```

#### Redis Backup (Optional)

Redis data is ephemeral (cache, Celery broker). For production data persistence:

```bash
# Force Redis save
podman exec redis redis-cli SAVE

# Copy Redis data file
podman cp redis:/data/dump.rdb /opt/senex-trader/backups/redis-$(date +%Y-%m-%d).rdb

# Restore Redis data
# Stop Redis, copy dump.rdb to data directory, restart
systemctl stop redis.service
cp /opt/senex-trader/backups/redis-2025-10-15.rdb /opt/senex-trader/data/redis/dump.rdb
systemctl start redis.service
```

## Troubleshooting

### Deployment Fails

**Issue:** Ansible fails to connect
```bash
# Check SSH connectivity
ssh root@your-domain.com

# Check SSH key
ssh-add -l

# Test with verbose output
ansible production -i inventory/hosts.yml -m ping -vvv --ask-vault-pass
```

**Issue:** Vault decryption fails
```bash
# Verify vault password
ansible-vault view inventory/staging-vault.yml

# Re-encrypt if needed
ansible-vault rekey inventory/staging-vault.yml
```

**Issue:** Podman login fails
```bash
# Manual login on server
ssh root@your-domain.com
podman login gitea.andermic.net
```

### Application Issues

**Issue:** Health check returns 500 error
```bash
# Check Django logs (Quadlet uses journalctl)
journalctl -u web.service -n 100

# Alternative: Direct container logs
podman logs web | tail -50

# Check database connection
podman exec postgres pg_isready

# Check Redis connection
podman exec redis redis-cli ping
```

**Issue:** WebSocket connections fail
```bash
# Check Daphne logs
journalctl -u web.service | grep -i websocket

# Verify WS_ALLOWED_ORIGINS in .env
cat /opt/senex-trader/.config/containers/systemd/.env | grep WS_ALLOWED_ORIGINS  # rootless
cat /etc/containers/systemd/.env | grep WS_ALLOWED_ORIGINS  # rootful

# Test WebSocket from browser console:
# const ws = new WebSocket('wss://your-domain.com/ws/streaming/');
# ws.onopen = () => console.log('Connected');
```

**Issue:** Celery tasks not processing
```bash
# Check Celery worker status
journalctl -u celery-worker.service -n 100

# Check Redis connection (Celery broker)
podman exec redis redis-cli ping

# Inspect active tasks from Django shell
podman exec -it web python manage.py shell
>>> from celery import current_app
>>> current_app.control.inspect().active()
```

### Network and Firewall Issues

**Issue:** External access to staging fails

**Symptoms:**
- Health check works locally: `curl http://localhost:8000/health/`
- External access fails: `curl http://10.0.0.100:8000/health/` (timeout)
- Nginx proxy at 10.0.0.209 cannot reach application

**Root Cause:** UFW blocking external traffic to Podman containers

**Solution (Staging only):**
```bash
# Allow Podman internal network for DNS
ssh root@10.0.0.100
ufw allow from 10.89.0.0/24

# Allow route forwarding from external nginx (staging only)
ufw route allow from 10.0.0.0/24 to any port 8000

# Check UFW status
ufw status verbose
```

**Note:** Ansible handles this automatically for staging (see deploy.yml:306-320).

### SSL Issues (Production)

**Issue:** Certbot fails to obtain certificate
```bash
# Check DNS resolution
dig your-domain.com

# Check firewall (ports 80, 443 open)
sudo ufw status

# Check Nginx configuration
sudo nginx -t

# Manually run certbot
sudo certbot --nginx -d your-domain.com --dry-run
```

**Issue:** Certificate renewal fails
```bash
# Test renewal
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal

# Check cron job
sudo systemctl status certbot.timer
```

## Security Considerations

### Secrets Management
- All secrets stored in Ansible Vault (AES-256 encrypted)
- Vault password never committed to git
- Different secrets for staging and production
- Secrets injected via environment variables

### Network Security
- Staging: Only port 8000 exposed (HTTP)
- Production: Only ports 22, 80, 443 open
- All services communicate via internal Docker network
- Database and Redis not exposed externally

### Container Security
- Podman rootless containers (when possible)
- Non-root user inside containers
- Health checks for all services
- Automatic restarts on failure
- Firewall rules managed via iptables-persistent (staging with Podman < 5.0)

### SSL/TLS
- Let's Encrypt certificates (production)
- Automatic renewal via certbot
- HTTPS redirect enforced
- Modern cipher suites

## Advanced Configuration

### Environment Variables

All environment variables are defined in `templates/env.j2` and sourced from vault files. To add new variables:

1. Add to `templates/env.j2`
2. Add to vault files (`staging-vault.yml`, `production-vault.yml`)
3. Re-run deployment

**Critical Environment Variables:**

- `ALLOWED_HOSTS` - Django allowed hosts (must include domain names)
- `CSRF_TRUSTED_ORIGINS` - Auto-generated from ALLOWED_HOSTS for HTTPS (see `senextrader/settings/production.py:43`)
- `WS_ALLOWED_ORIGINS` - WebSocket allowed origins (must match domain)
- `APP_BASE_URL` - Base URL for absolute links
- `APP_DIR` - Application directory for bind mounts (staging/production: `/opt/senex-trader`)

**Staging-Specific Settings:**

Staging runs behind nginx reverse proxy that handles SSL termination. Configuration in `senextrader/settings/staging.py`:

```python
# Trust X-Forwarded-Proto header from proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Disable forced SSL redirect (nginx handles it)
SECURE_SSL_REDIRECT = False
```

### Resource Limits

**Quadlet Note:** Resource limits are managed via systemd unit drop-ins, not Quadlet .container files directly.

To add resource limits:
```bash
# Create systemd override for web service
mkdir -p /etc/systemd/system/web.service.d/
cat > /etc/systemd/system/web.service.d/resources.conf <<EOF
[Service]
CPUQuota=100%
MemoryMax=1G
EOF

systemctl daemon-reload
systemctl restart web.service
```

For rootless (production):
```bash
mkdir -p ~/.config/systemd/user/web.service.d/
cat > ~/.config/systemd/user/web.service.d/resources.conf <<EOF
[Service]
CPUQuota=100%
MemoryMax=1G
EOF

systemctl --user daemon-reload
systemctl --user restart web.service
```

### Scaling Services

**Horizontal scaling (multiple instances):**

Quadlet doesn't support replicas like Compose. For multiple instances:
1. Create multiple .container files (web-1.container, web-2.container)
2. Add Nginx upstream with multiple backends
3. Or migrate to Kubernetes for native replica support

## Reference Documentation

For comprehensive deployment planning and advanced scenarios, see:

- **senextrader_docs/deployment/README.md** - Complete deployment documentation
- **senextrader_docs/deployment/00-OVERVIEW.md** - Architecture overview
- **senextrader_docs/deployment/04-SERVICE-CONFIGURATION.md** - Service configs
- **senextrader_docs/deployment/10-IMPLEMENTATION-PHASES.md** - Phased deployment plan

## Support

### Getting Help

1. Check logs for error messages
2. Review troubleshooting section above
3. Consult reference documentation
4. Check container health: `podman ps`

### Useful Commands

```bash
# Ansible check mode (dry run)
ansible-playbook deploy.yml --check --limit staging --ask-vault-pass

# Ansible verbose output
ansible-playbook deploy.yml --limit staging --ask-vault-pass -vvv

# List vault variables
ansible-vault view inventory/staging-vault.yml

# Edit vault
ansible-vault edit inventory/staging-vault.yml

# Change vault password
ansible-vault rekey inventory/staging-vault.yml
```

## License

Internal documentation for Senex Trader deployment. Proprietary and confidential.

---

**Last Updated:** 2025-10-15
**Version:** 2.0 (Quadlet Migration)
**Status:** Production Ready (Staging Verified)
