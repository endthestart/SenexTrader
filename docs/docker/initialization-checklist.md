# Initialization Checklist

## Overview

This document provides step-by-step initialization procedures for deploying Senex Trader containers, from first-time setup to production deployment verification.

---

## Pre-Deployment Checklist

### 1. Required Files

- [ ] **Dockerfile** (`docker/Dockerfile`)
- [ ] **Dockerfile.dev** (`docker/Dockerfile.dev`)
- [ ] **docker-compose.yml** (base configuration)
- [ ] **docker-compose.dev.yml** (development overrides)
- [ ] **docker-compose.prod.yml** (production overrides)
- [ ] **.dockerignore** (build context exclusions)
- [ ] **entrypoint.sh** (`docker/entrypoint.sh`)
- [ ] **.env.example** (environment variable template)
- [ ] **requirements.txt** (Python dependencies)

### 2. Required Secrets Generated

- [ ] **SECRET_KEY** (Django secret key)
  ```bash
  python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
  ```

- [ ] **FIELD_ENCRYPTION_KEY** (Fernet encryption key)
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

- [ ] **DB_PASSWORD** (PostgreSQL password)
  ```bash
  openssl rand -base64 32
  ```

- [ ] **TASTYTRADE_CLIENT_ID** (from TastyTrade developer portal)
- [ ] **TASTYTRADE_CLIENT_SECRET** (from TastyTrade developer portal)

### 3. Environment Configuration

- [ ] **.env.production** created from template
- [ ] All required variables set (see `environment-variables.md`)
- [ ] Secrets stored securely (not in version control)
- [ ] `.gitignore` updated to exclude `.env*` files

### 4. Infrastructure Ready

- [ ] **Podman** installed (`podman --version`)
- [ ] **podman-compose** installed (`podman-compose --version`)
- [ ] **Reverse proxy** configured (Nginx/Traefik) for SSL
- [ ] **Domain DNS** configured (A record pointing to server)
- [ ] **SSL certificates** obtained (Let's Encrypt, etc.)

---

## Development Environment Initialization

### Step 1: Create Development Environment File

```bash
cp .env.example .env
```

**Edit .env** with development values:
```bash
ENVIRONMENT=development
SECRET_KEY=django-insecure-dev-key-CHANGE-THIS
FIELD_ENCRYPTION_KEY=dev-key-CHANGE-THIS
TASTYTRADE_BASE_URL=https://api.cert.tastyworks.com  # Sandbox
```

### Step 2: Build Development Images

```bash
podman-compose -f docker-compose.yml -f docker-compose.dev.yml build
```

**Expected Output**:
```
Building redis
Successfully tagged senex_redis:dev
Building web
Successfully tagged senextrader:dev
Building celery_worker
Successfully tagged senextrader:dev
Building celery_beat
Successfully tagged senextrader:dev
```

### Step 3: Start Development Services

```bash
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**Expected Output**:
```
Creating senex_redis_dev ... done
Creating senex_web_dev ... done
Creating senex_celery_worker_dev ... done
Creating senex_celery_beat_dev ... done
```

### Step 4: Verify Services Running

**Check container status**:
```bash
podman-compose ps
```

**Expected Output**:
```
NAME                   STATUS    PORTS
senex_redis_dev        Up        6379/tcp
senex_web_dev          Up        0.0.0.0:8000->8000/tcp
senex_celery_worker    Up
senex_celery_beat      Up
```

### Step 5: Access Application

**Open browser**: http://localhost:8000

**Expected**: Django admin login page or homepage

### Step 6: Create Superuser (Interactive)

```bash
podman-compose exec web python manage.py createsuperuser
```

**Prompts**:
```
Username: admin
Email: [email protected]
Password: ****
Password (again): ****
Superuser created successfully.
```

### Step 7: Access Admin Interface

**URL**: http://localhost:8000/admin

**Login**: Use superuser credentials from Step 6

---

## Production Environment Initialization

### Step 1: Prepare Server

**Install Podman**:
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y podman podman-compose

# Verify
podman --version
podman-compose --version
```

**Create Application User**:
```bash
sudo useradd -m -s /bin/bash senex-app
sudo su - senex-app
```

**Enable Systemd Linger** (services start without login):
```bash
loginctl enable-linger senex-app
```

### Step 2: Clone Repository

```bash
cd ~
git clone https://github.com/yourusername/senextrader.git
cd senextrader
```

### Step 3: Create Production Environment File

```bash
cp .env.production.example .env.production
```

**Edit .env.production** with production values:
```bash
# CRITICAL: Set all required secrets
ENVIRONMENT=production
SECRET_KEY=<GENERATE_WITH_COMMAND>
FIELD_ENCRYPTION_KEY=<GENERATE_WITH_COMMAND>
DB_PASSWORD=<GENERATE_WITH_COMMAND>
TASTYTRADE_CLIENT_ID=<FROM_PORTAL>
TASTYTRADE_CLIENT_SECRET=<FROM_PORTAL>

# Production URLs
ALLOWED_HOSTS=your-domain.com,api.your-domain.com
WS_ALLOWED_ORIGINS=https://your-domain.com,https://api.your-domain.com
APP_BASE_URL=https://your-domain.com

# Database
DB_NAME=senextrader
DB_USER=senex_user
DB_HOST=postgres

# Security
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
```

**Verify Required Variables**:
```bash
source .env.production
./scripts/validate-env.sh  # See environment-variables.md
```

### Step 4: Build Production Images

```bash
podman-compose \
  --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  build
```

**Expected Duration**: 5-10 minutes (first build)

**Expected Output**:
```
Building postgres
Successfully tagged postgres:16-alpine
Building redis
Successfully tagged redis:7-alpine
Building web
Successfully tagged senextrader:latest
Building celery_worker
Successfully tagged senextrader:latest
Building celery_beat
Successfully tagged senextrader:latest
```

### Step 5: Create Volumes (Explicit Creation)

```bash
podman volume create postgres_data
podman volume create redis_data
podman volume create logs
podman volume create staticfiles
podman volume create celerybeat_schedule
```

**Verify**:
```bash
podman volume ls | grep senex
```

### Step 6: Start Services

```bash
podman-compose \
  --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d
```

**Expected Output**:
```
Creating senex_postgres ... done
Creating senex_redis ... done
Creating senex_web ... done
Creating senex_celery_worker ... done
Creating senex_celery_beat ... done
```

### Step 7: Monitor Startup Logs

**All services**:
```bash
podman-compose logs -f
```

**Single service**:
```bash
podman-compose logs -f web
```

**Expected Logs (web service)**:
```
Waiting for PostgreSQL...
PostgreSQL is ready!
Waiting for Redis...
Redis is ready!
Running database migrations...
Operations to perform:
  Apply all migrations: accounts, admin, auth, ...
Running migrations:
  Applying accounts.0001_initial... OK
  Applying trading.0001_initial... OK
  ...
Collecting static files...
Collected 150 static files in 2s.
Initialization complete!
Starting Daphne ASGI server...
Starting server at http://0.0.0.0:8000
```

### Step 8: Verify Services Health

**Check container health**:
```bash
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Health}}"
```

**Expected Output**:
```
NAMES                STATUS              HEALTH
senex_postgres       Up 2 minutes        healthy
senex_redis          Up 2 minutes        healthy
senex_web            Up 2 minutes        healthy
senex_celery_worker  Up 2 minutes
senex_celery_beat    Up 2 minutes
```

**Test health endpoint**:
```bash
curl http://localhost:8000/health/
```

**Expected Response**:
```json
{"status": "healthy"}
```

### Step 9: Create Superuser (Production)

**Method 1: Interactive**:
```bash
podman-compose exec web python manage.py createsuperuser
```

**Method 2: Non-Interactive** (for automation):
```bash
podman-compose exec -T web python manage.py shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', '[email protected]', 'changeme')
    print('Superuser created')
else:
    print('Superuser already exists')
EOF
```

### Step 10: Test Application

**Internal test** (from server):
```bash
curl -I http://localhost:8000/admin/
```

**Expected Response**:
```
HTTP/1.1 302 Found
Location: /admin/login/?next=/admin/
```

**External test** (from browser):
- URL: https://your-domain.com/admin/
- Expected: Admin login page
- Login with superuser credentials

### Step 11: Configure Systemd (Auto-Start)

**Generate systemd unit files**:
```bash
cd ~/senextrader

# Generate for all services
podman generate systemd \
  --name senex_postgres \
  --files \
  --new

podman generate systemd \
  --name senex_redis \
  --files \
  --new

podman generate systemd \
  --name senex_web \
  --files \
  --new

podman generate systemd \
  --name senex_celery_worker \
  --files \
  --new

podman generate systemd \
  --name senex_celery_beat \
  --files \
  --new
```

**Install unit files**:
```bash
mkdir -p ~/.config/systemd/user/
cp container-*.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable services
systemctl --user enable container-senex_postgres.service
systemctl --user enable container-senex_redis.service
systemctl --user enable container-senex_web.service
systemctl --user enable container-senex_celery_worker.service
systemctl --user enable container-senex_celery_beat.service

# Verify
systemctl --user list-unit-files | grep senex
```

### Step 12: Test Auto-Start

**Reboot server**:
```bash
sudo reboot
```

**After reboot, verify services**:
```bash
systemctl --user status container-senex_web.service
podman ps
```

**Expected**: All services running automatically

---

## Database Migration Verification

### Check Migration Status

```bash
podman-compose exec web python manage.py showmigrations
```

**Expected Output**:
```
accounts
 [X] 0001_initial
 [X] 0002_tradingaccount_oauth_token
 ...
trading
 [X] 0001_initial
 [X] 0002_position_pnl
 ...
```

### Apply Pending Migrations (If Any)

```bash
podman-compose exec web python manage.py migrate
```

---

## Static Files Verification

### Check Static Files Collected

```bash
# Inside container
podman-compose exec web ls /app/staticfiles/

# Expected: admin/, css/, js/, staticfiles.json
```

### Test Static File Serving

**Request static file**:
```bash
curl -I http://localhost:8000/static/css/dark-theme.css
```

**Expected Headers**:
```
HTTP/1.1 200 OK
Content-Type: text/css
Content-Encoding: gzip
Cache-Control: public, max-age=31536000, immutable
```

---

## Celery Verification

### Check Celery Worker Status

```bash
podman-compose exec celery_worker celery -A senextrader inspect active
```

**Expected Output**:
```json
{
  "celery@hostname": []
}
```

### Check Celery Beat Schedule

```bash
podman-compose exec celery_beat celery -A senextrader inspect scheduled
```

**Expected Output**:
```json
{
  "celery@hostname": {
    "scheduled": [
      {
        "eta": "2025-01-15T10:00:00+00:00",
        "priority": 6,
        "request": {
          "name": "trading.tasks.automated_daily_trade_cycle",
          ...
        }
      }
    ]
  }
}
```

### Test Manual Task Execution

```bash
podman-compose exec web python manage.py shell
```

**In Django shell**:
```python
from trading.tasks import sync_positions_task
result = sync_positions_task.delay()
result.get(timeout=10)
# Output: Task result
```

---

## Redis Verification

### Check Redis Connection

```bash
podman-compose exec redis redis-cli ping
```

**Expected**: `PONG`

### Check Redis Keys

```bash
podman-compose exec redis redis-cli
```

**In Redis CLI**:
```redis
SELECT 0  # Cache database
DBSIZE
# (integer) 0 or more

SELECT 2  # Celery broker
DBSIZE
# (integer) 0 or more
```

---

## PostgreSQL Verification

### Check Database Connection

```bash
podman-compose exec postgres psql -U senex_user -d senextrader -c "SELECT 1;"
```

**Expected Output**:
```
 ?column?
----------
        1
(1 row)
```

### Check Tables Created

```bash
podman-compose exec postgres psql -U senex_user -d senextrader -c "\dt"
```

**Expected Output** (partial):
```
 Schema |            Name             | Type  |   Owner
--------+-----------------------------+-------+------------
 public | accounts_tradingaccount     | table | senex_user
 public | trading_position            | table | senex_user
 public | trading_trade               | table | senex_user
 ...
```

---

## Logging Verification

### Check Log Files

```bash
# List log files
podman volume inspect logs | jq -r '.[0].Mountpoint'
sudo ls -la <mountpoint-path>

# Or view directly
podman-compose exec web ls -la /var/log/senextrader/
```

**Expected Files**:
- application.log
- errors.log
- trading.log
- security.log

### Tail Logs

```bash
podman-compose exec web tail -f /var/log/senextrader/application.log
```

---

## Security Verification

### Check Non-Root User

```bash
podman-compose exec web whoami
```

**Expected**: `senex` (not `root`)

### Check File Permissions

```bash
podman-compose exec web ls -la /app/
```

**Expected**: All files owned by `senex:senex`

### Check SSL Configuration

**Test SSL redirect**:
```bash
curl -I http://your-domain.com
```

**Expected**:
```
HTTP/1.1 301 Moved Permanently
Location: https://your-domain.com/
```

**Test HSTS header**:
```bash
curl -I https://your-domain.com
```

**Expected**:
```
HTTP/1.1 200 OK
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

---

## Performance Verification

### Load Test

**Install Apache Bench**:
```bash
sudo apt-get install apache2-utils
```

**Run load test**:
```bash
ab -n 1000 -c 10 http://localhost:8000/health/
```

**Expected**:
```
Requests per second:    500-1000 [#/sec]
Time per request:       10-20 [ms]
Failed requests:        0
```

### Resource Usage

**Check container stats**:
```bash
podman stats --no-stream
```

**Expected** (after startup):
```
CONTAINER       CPU%    MEM USAGE / LIMIT   MEM%
senex_postgres  5%      200MB / 4GB         5%
senex_redis     2%      50MB / 1GB          5%
senex_web       10%     300MB / 1GB         30%
senex_worker    15%     500MB / 2GB         25%
senex_beat      1%      100MB / 512MB       20%
```

---

## Troubleshooting Common Issues

### Issue: Container Exits Immediately

**Check logs**:
```bash
podman-compose logs web
```

**Common causes**:
- Missing required environment variables
- Database connection failure
- Syntax error in settings

**Solution**: Fix issue and restart
```bash
podman-compose up -d
```

### Issue: Database Connection Refused

**Symptoms**: `django.db.utils.OperationalError: could not connect to server`

**Check**:
```bash
podman-compose exec postgres pg_isready
```

**Solution**: Wait for PostgreSQL to be ready
```bash
# PostgreSQL takes 10-30 seconds to start
podman-compose logs postgres
# Wait for: "database system is ready to accept connections"
```

### Issue: Static Files Not Loading

**Symptoms**: 404 errors for /static/ URLs

**Check**:
```bash
podman-compose exec web ls /app/staticfiles/
```

**Solution**: Run collectstatic manually
```bash
podman-compose exec web python manage.py collectstatic --noinput
```

### Issue: Celery Tasks Not Executing

**Check worker status**:
```bash
podman-compose logs celery_worker
```

**Solution**: Restart worker
```bash
podman-compose restart celery_worker
```

---

## Backup Procedures

### Database Backup

**Create backup**:
```bash
podman-compose exec -T postgres pg_dump -U senex_user senextrader | gzip > backup_$(date +%Y%m%d).sql.gz
```

**Restore backup**:
```bash
gunzip -c backup_20250115.sql.gz | podman-compose exec -T postgres psql -U senex_user senextrader
```

### Volume Backup

**Export volume**:
```bash
podman volume export postgres_data -o postgres_data_backup.tar
```

**Import volume**:
```bash
podman volume import postgres_data postgres_data_backup.tar
```

---

## Monitoring Setup

### Log Aggregation

**Ship logs to external service**:
```bash
# Example: ship to Papertrail
podman run -d \
  --name log-shipper \
  --volumes-from senex_web \
  papertrail/remote_syslog
```

### Metrics Collection

**Prometheus metrics** (future enhancement):
```yaml
# docker-compose.yml addition
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
```

---

## Summary Checklist

### Pre-Deployment
- [ ] All required files created
- [ ] Secrets generated
- [ ] Environment configured
- [ ] Infrastructure ready

### Development Setup
- [ ] Images built
- [ ] Services started
- [ ] Application accessible
- [ ] Superuser created

### Production Setup
- [ ] Server prepared
- [ ] Repository cloned
- [ ] Production env configured
- [ ] Images built
- [ ] Services started
- [ ] Health verified
- [ ] Superuser created
- [ ] Systemd configured
- [ ] Auto-start verified

### Verification
- [ ] Database migrations applied
- [ ] Static files collected
- [ ] Celery tasks running
- [ ] Redis connected
- [ ] PostgreSQL connected
- [ ] Logs writing
- [ ] Security configured
- [ ] Performance acceptable

### Post-Deployment
- [ ] Backups configured
- [ ] Monitoring setup
- [ ] Documentation updated
- [ ] Team trained

**Next Steps**: See `implementation-requirements.md` for code changes needed to support containerization.
