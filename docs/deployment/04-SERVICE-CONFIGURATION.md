# Service Configuration Details

## Overview

This guide provides detailed configuration for all Senex Trader services. Each service section includes:
- Configuration parameters and tuning
- Environment variables
- Volume mounts and persistence
- Resource limits
- Health checks
- Common issues and troubleshooting

## PostgreSQL Database

### Container Configuration

**Quadlet File**: `~/.config/containers/systemd/postgres.container`

```ini
[Unit]
Description=PostgreSQL Database - Senex Trader
After=network-online.target
Documentation=https://www.postgresql.org/docs/16/

[Container]
Image=docker.io/library/postgres:16-alpine
ContainerName=postgres
AutoUpdate=registry

# Network
Network=senex_net.network
PublishPort=127.0.0.1:5432:5432

# Persistent storage with SELinux label
Volume=postgres_data:/var/lib/postgresql/data:Z

# Environment variables
Environment=POSTGRES_DB=senex_trader
Environment=POSTGRES_USER=senex_user
Environment=POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C
Secret=db_password,type=env,target=POSTGRES_PASSWORD

# PostgreSQL tuning via command-line args (adjust for your server RAM)
# NOTE: The postgres:16-alpine image ignores POSTGRES_* env vars for tuning
# These settings are for 8GB RAM server
Exec=postgres \
  -c shared_buffers=2GB \
  -c effective_cache_size=6GB \
  -c work_mem=64MB \
  -c maintenance_work_mem=512MB \
  -c max_connections=200 \
  -c checkpoint_completion_target=0.9 \
  -c wal_buffers=16MB \
  -c random_page_cost=1.1 \
  -c effective_io_concurrency=200 \
  -c min_wal_size=1GB \
  -c max_wal_size=4GB

# Alternative: Mount a postgresql.conf file
# Volume=%h/senex-trader/postgresql.conf:/etc/postgresql/postgresql.conf:ro,Z
# Exec=postgres -c config_file=/etc/postgresql/postgresql.conf

# Health check
HealthCmd=pg_isready -U senex_user -d senex_trader
HealthInterval=10s
HealthTimeout=5s
HealthRetries=3
HealthStartPeriod=30s

# Resource limits
Memory=4G
MemorySwap=6G
CPUQuota=200%

# Security
User=postgres
NoNewPrivileges=true

[Service]
Restart=always
RestartSec=10
TimeoutStartSec=120
TimeoutStopSec=60

# Graceful shutdown
ExecStop=/usr/bin/podman stop -t 60 postgres

[Install]
WantedBy=default.target
```

### PostgreSQL Tuning Parameters

**For 4GB RAM Server**:
```bash
shared_buffers = 1GB              # 25% of RAM
effective_cache_size = 3GB        # 75% of RAM
work_mem = 32MB                   # Per query operation
maintenance_work_mem = 256MB      # For VACUUM, CREATE INDEX
```

**For 8GB RAM Server**:
```bash
shared_buffers = 2GB
effective_cache_size = 6GB
work_mem = 64MB
maintenance_work_mem = 512MB
```

**For 16GB RAM Server**:
```bash
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 128MB
maintenance_work_mem = 1GB
```

### SSL Configuration

**Enable SSL connections** (production requirement):

1. **Generate certificates** (or use existing):
```bash
# Self-signed for testing
openssl req -new -x509 -days 365 -nodes -text \
  -out server.crt -keyout server.key -subj "/CN=postgres"

chmod 600 server.key
chown 999:999 server.key server.crt  # postgres user UID
```

2. **Mount certificates**:
```ini
Volume=/etc/ssl/postgres/server.crt:/var/lib/postgresql/server.crt:ro,Z
Volume=/etc/ssl/postgres/server.key:/var/lib/postgresql/server.key:ro,Z
```

3. **Add SSL parameters**:
```ini
Exec=postgres \
  -c ssl=on \
  -c ssl_cert_file=/var/lib/postgresql/server.crt \
  -c ssl_key_file=/var/lib/postgresql/server.key \
  -c ssl_min_protocol_version=TLSv1.2
```

4. **Django connection** (`production.py`):
```python
DATABASES = {
    'default': {
        'OPTIONS': {
            'sslmode': 'require',
        }
    }
}
```

### Connection Pooling with PgBouncer

**Why**: Reduces PostgreSQL memory usage from ~200 connections to ~25

**Installation** (on PostgreSQL server):
```bash
sudo apt install pgbouncer
```

**Configuration** (`/etc/pgbouncer/pgbouncer.ini`):
```ini
[databases]
senex_trader = host=localhost port=5432 dbname=senex_trader

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

# Critical: Transaction pooling for Django
pool_mode = transaction
max_client_conn = 200
default_pool_size = 25
reserve_pool_size = 5
reserve_pool_timeout = 3

# Logging
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1

# Timeouts
server_idle_timeout = 600
server_lifetime = 3600
```

**User list** (`/etc/pgbouncer/userlist.txt`):
```
"senex_user" "md5<MD5_HASH>"
```

Generate hash:
```bash
echo -n "passwordsenex_user" | md5sum
# Use output in userlist.txt as: "senex_user" "md5<hash>"
```

**Django configuration** (with PgBouncer):
```python
DATABASES = {
    'default': {
        'PORT': '6432',  # PgBouncer port, not PostgreSQL
        'CONN_MAX_AGE': None,  # Let PgBouncer handle pooling
        'DISABLE_SERVER_SIDE_CURSORS': True,  # Required for transaction pooling
    }
}
```

**Start PgBouncer**:
```bash
sudo systemctl enable pgbouncer
sudo systemctl start pgbouncer
```

### Backup Configuration

**WAL Archiving** (for PITR):

1. **Create archive directory**:
```bash
mkdir -p /var/backups/postgresql/wal_archive
chown senex:senex /var/backups/postgresql/wal_archive
```

2. **Add to PostgreSQL config**:
```ini
Exec=postgres \
  -c wal_level=replica \
  -c archive_mode=on \
  -c archive_command='test ! -f /var/backups/postgresql/wal_archive/%f && cp %p /var/backups/postgresql/wal_archive/%f' \
  -c archive_timeout=300
```

3. **Mount archive directory**:
```ini
Volume=/var/backups/postgresql/wal_archive:/var/backups/postgresql/wal_archive:z
```

## Redis Cache and Broker

### Container Configuration

**Quadlet File**: `~/.config/containers/systemd/redis.container`

```ini
[Unit]
Description=Redis Cache and Broker - Senex Trader
After=network-online.target

[Container]
Image=docker.io/library/redis:7-alpine
ContainerName=redis
AutoUpdate=registry

# Network
Network=senex_net.network
PublishPort=127.0.0.1:6379:6379

# Persistent storage
Volume=redis_data:/data:Z

# Custom configuration
Volume=%h/senex-trader/configs/redis.conf:/usr/local/etc/redis/redis.conf:ro,z

# Redis password via secret
Secret=redis_password,type=env,target=REDIS_PASSWORD

# Start with custom config
Exec=redis-server /usr/local/etc/redis/redis.conf --requirepass ${REDIS_PASSWORD}

# Health check
HealthCmd=redis-cli --no-auth-warning -a ${REDIS_PASSWORD} ping
HealthInterval=10s
HealthTimeout=3s
HealthRetries=3

# Resource limits
Memory=1G
CPUQuota=100%

# Security
User=redis
NoNewPrivileges=true

[Service]
Restart=always
RestartSec=10
TimeoutStopSec=30

# Graceful shutdown (save data before stop)
ExecStop=/bin/sh -c '/usr/bin/podman exec redis redis-cli -a ${REDIS_PASSWORD} SAVE && /usr/bin/podman stop -t 30 redis'

[Install]
WantedBy=default.target
```

### Redis Configuration File

**Location**: `~/senex-trader/configs/redis.conf`

```conf
# Network
bind 0.0.0.0
port 6379
protected-mode yes
tcp-backlog 511
timeout 300
tcp-keepalive 300

# SECURITY - Password set via command line
# requirepass will be overridden by --requirepass flag

# General
daemonize no
supervised no
loglevel notice
databases 16

# Snapshotting (RDB persistence)
save 900 1       # After 900 sec (15 min) if at least 1 key changed
save 300 10      # After 300 sec (5 min) if at least 10 keys changed
save 60 10000    # After 60 sec if at least 10000 keys changed

stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir /data

# Replication (uncomment for Redis Sentinel setup)
# replica-serve-stale-data yes
# replica-read-only yes
# repl-diskless-sync no
# repl-diskless-sync-delay 5

# Memory management
maxmemory 900mb                    # Leave some room for overhead
maxmemory-policy allkeys-lru       # Evict least recently used keys
maxmemory-samples 5

# Append Only File (AOF persistence)
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec              # Balance between performance and durability
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

# Lua scripting
lua-time-limit 5000

# Slow log
slowlog-log-slower-than 10000     # 10ms
slowlog-max-len 128

# Event notification (for Celery)
notify-keyspace-events Ex         # Expired events

# Advanced config
hash-max-ziplist-entries 512
hash-max-ziplist-value 64
list-max-ziplist-size -2
set-max-intset-entries 512
zset-max-ziplist-entries 128
zset-max-ziplist-value 64

# Active rehashing
activerehashing yes

# Client output buffer limits
client-output-buffer-limit normal 0 0 0
client-output-buffer-limit replica 256mb 64mb 60
client-output-buffer-limit pubsub 32mb 8mb 60

# Performance
hz 10
dynamic-hz yes

# Lazy freeing
lazyfree-lazy-eviction no
lazyfree-lazy-expire no
lazyfree-lazy-server-del no
replica-lazy-flush no
```

### Redis Database Usage

| Database | Purpose | Django Setting | Typical Size |
|----------|---------|----------------|--------------|
| 0 | Django cache | `CACHES['default']` | 100-500MB |
| 1 | Django Channels | `CHANNEL_LAYERS` | 10-50MB |
| 2 | Celery broker | `CELERY_BROKER_URL` | 50-200MB |
| 3 | Celery results | `CELERY_RESULT_BACKEND` | 50-100MB |

**Total**: ~300-850MB (configure maxmemory accordingly)

### Redis Monitoring

**Check memory usage**:
```bash
podman exec redis redis-cli -a PASSWORD INFO memory | grep used_memory_human
```

**Check database sizes**:
```bash
for db in {0..3}; do
  echo "DB $db:"
  podman exec redis redis-cli -a PASSWORD -n $db DBSIZE
done
```

**Monitor slow queries**:
```bash
podman exec redis redis-cli -a PASSWORD SLOWLOG GET 10
```

## Django/Daphne Application

### Container Configuration

**Quadlet File**: `~/.config/containers/systemd/django.container`

```ini
[Unit]
Description=Django/Daphne ASGI Server - Senex Trader
After=network-online.target
Requires=postgres.service redis.service
After=postgres.service redis.service

[Container]
Image=registry.example.com/senex-trader:latest
ContainerName=django
AutoUpdate=registry

# Network
Network=senex_net.network
PublishPort=8000:8000

# Environment
EnvironmentFile=/etc/senex-trader/.env
Environment=DJANGO_SETTINGS_MODULE=senex_trader.settings.production

# Shared volumes for static/media files (served by Nginx)
Volume=%h/senex-trader/static:/app/staticfiles:z
Volume=%h/senex-trader/media:/app/media:z

# Health check
HealthCmd=curl -f http://localhost:8000/health/ || exit 1
HealthInterval=30s
HealthTimeout=10s
HealthRetries=3
HealthStartPeriod=60s
HealthOnFailure=kill

# Resource limits
Memory=1536M
MemorySwap=2G
CPUQuota=100%

# Security
User=django
WorkingDir=/app
NoNewPrivileges=true

# Daphne command
Exec=daphne \
  -b 0.0.0.0 \
  -p 8000 \
  --access-log - \
  --proxy-headers \
  senex_trader.asgi:application

[Service]
Restart=always
RestartSec=10
TimeoutStartSec=300
TimeoutStopSec=60

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=django

[Install]
WantedBy=default.target
```

### Environment Variables

**File**: `/etc/senex-trader/.env`

```bash
# Django Core
DJANGO_SETTINGS_MODULE=senex_trader.settings.production
SECRET_KEY=<from_ansible_vault>
FIELD_ENCRYPTION_KEY=<from_ansible_vault>
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
DEBUG=False

# Database (via PgBouncer if configured)
DB_NAME=senex_trader
DB_USER=senex_user
DB_PASSWORD=<from_ansible_vault>
DB_HOST=postgres
DB_PORT=5432

# Redis
REDIS_URL=redis://:PASSWORD@redis:6379/0

# Celery
CELERY_BROKER_URL=redis://:PASSWORD@redis:6379/2
CELERY_RESULT_BACKEND=redis://:PASSWORD@redis:6379/3

# TastyTrade
TASTYTRADE_CLIENT_ID=<from_ansible_vault>
TASTYTRADE_CLIENT_SECRET=<from_ansible_vault>
TASTYTRADE_BASE_URL=https://api.tastyworks.com

# WebSocket
WS_ALLOWED_ORIGINS=your-domain.com,www.your-domain.com

# Email (optional)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@your-domain.com
EMAIL_HOST_PASSWORD=<from_ansible_vault>
DEFAULT_FROM_EMAIL=noreply@your-domain.com

# Monitoring (optional)
SENTRY_DSN=<from_ansible_vault>
```

### Django Management Commands

**Run via Podman exec**:

```bash
# Migrations
podman exec django python manage.py migrate

# Create superuser
podman exec -it django python manage.py createsuperuser

# Collect static files
podman exec django python manage.py collectstatic --noinput

# Database shell
podman exec -it django python manage.py dbshell

# Django shell
podman exec -it django python manage.py shell

# Check configuration
podman exec django python manage.py check --deploy
```

## Celery Worker

### Container Configuration

**Quadlet File**: `~/.config/containers/systemd/celery-worker.container`

```ini
[Unit]
Description=Celery Worker - Senex Trader
After=redis.service django.service
Requires=redis.service

[Container]
Image=registry.example.com/senex-trader:latest
ContainerName=celery-worker
AutoUpdate=registry

# Network
Network=senex_net.network

# Environment
EnvironmentFile=/etc/senex-trader/.env
Environment=DJANGO_SETTINGS_MODULE=senex_trader.settings.production

# Celery worker command
Exec=celery -A senex_trader worker \
  --queues=trading,accounts,services \
  --loglevel=info \
  --concurrency=4 \
  --max-tasks-per-child=100 \
  --time-limit=3600 \
  --soft-time-limit=1800 \
  --prefetch-multiplier=4

# Resource limits
Memory=2G
MemorySwap=3G
CPUQuota=200%

# Security
User=django
WorkingDir=/app
NoNewPrivileges=true

[Service]
Restart=always
RestartSec=10
TimeoutStartSec=60
TimeoutStopSec=300

# Graceful shutdown (wait for tasks to complete)
KillSignal=SIGTERM
KillMode=mixed

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=celery-worker

[Install]
WantedBy=default.target
```

### Celery Monitoring

**Inspect active tasks**:
```bash
podman exec django celery -A senex_trader inspect active
```

**Check worker stats**:
```bash
podman exec django celery -A senex_trader inspect stats
```

**Monitor queue lengths**:
```bash
for queue in trading accounts services; do
  echo "$queue: $(podman exec redis redis-cli -a PASSWORD LLEN $queue)"
done
```

### Celery Flower (Optional Monitoring UI)

**Quadlet File**: `~/.config/containers/systemd/celery-flower.container`

```ini
[Unit]
Description=Celery Flower Monitoring - Senex Trader
After=redis.service

[Container]
Image=registry.example.com/senex-trader:latest
ContainerName=celery-flower
Network=senex_net.network
PublishPort=127.0.0.1:5555:5555

EnvironmentFile=/etc/senex-trader/.env

Exec=celery -A senex_trader flower \
  --port=5555 \
  --basic_auth=admin:PASSWORD

Memory=512M

[Service]
Restart=always

[Install]
WantedBy=default.target
```

Access via: `http://localhost:5555` (configure Nginx reverse proxy for external access)

## Celery Beat Scheduler

### Container Configuration

**Quadlet File**: `~/.config/containers/systemd/celery-beat.container`

```ini
[Unit]
Description=Celery Beat Scheduler - Senex Trader
After=redis.service django.service
Requires=redis.service

# CRITICAL: Only ONE beat instance should run!
Conflicts=celery-beat@.service

[Container]
Image=registry.example.com/senex-trader:latest
ContainerName=celery-beat
AutoUpdate=registry

# Network
Network=senex_net.network

# Environment
EnvironmentFile=/etc/senex-trader/.env
Environment=DJANGO_SETTINGS_MODULE=senex_trader.settings.production

# Celery beat command (using Django database scheduler)
Exec=celery -A senex_trader beat \
  --loglevel=info \
  --scheduler=django_celery_beat.schedulers:DatabaseScheduler

# Resource limits (beat is lightweight)
Memory=512M

# Security
User=django
WorkingDir=/app
NoNewPrivileges=true

[Service]
Restart=always
RestartSec=10
TimeoutStartSec=60

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=celery-beat

[Install]
WantedBy=default.target
```

### Scheduled Tasks Verification

**Check in Django admin**:
1. Navigate to `/admin/django_celery_beat/periodictask/`
2. Verify all expected tasks are present:
   - `monitor_positions_for_dte_closure` (9:30 AM daily)
   - `automated_daily_trade_cycle` (10:00 AM weekdays)
   - `monitor_open_orders` (every 5 minutes)
   - `sync_positions_task` (every 10 minutes)
   - etc.

**Check via shell**:
```bash
podman exec django python manage.py shell << EOF
from django_celery_beat.models import PeriodicTask
for task in PeriodicTask.objects.filter(enabled=True):
    print(f"{task.name}: {task.crontab or task.interval}")
EOF
```

## Nginx Reverse Proxy

### Installation (Host System)

```bash
# Install Nginx on host (not containerized for better performance)
sudo apt install nginx certbot python3-certbot-nginx

# Enable and start
sudo systemctl enable nginx
sudo systemctl start nginx
```

### Configuration

**File**: `/etc/nginx/sites-available/your-domain.com`

See `configs/nginx/your-domain.com.conf` for complete configuration.

**Key sections**:

1. **Upstream backends**:
```nginx
upstream django_backend {
    server 127.0.0.1:8000 max_fails=3 fail_timeout=30s;
    # For HA: add more instances with ip_hash
    keepalive 32;
}
```

2. **SSL certificates** (Let's Encrypt):
```nginx
ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
```

3. **WebSocket support**:
```nginx
location /ws/ {
    proxy_pass http://django_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400s;
}
```

4. **Rate limiting**:
```nginx
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;
location /accounts/login/ {
    limit_req zone=login_limit burst=2 nodelay;
    proxy_pass http://django_backend;
}
```

**Enable site**:
```bash
sudo ln -s /etc/nginx/sites-available/your-domain.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Service Startup Order

**Correct dependency chain**:

1. **Network**: Podman network created first
2. **PostgreSQL**: Database must be ready before Django
3. **Redis**: Cache/broker must be ready before Django/Celery
4. **Django**: Application starts after DB + Redis
5. **Celery Worker**: Starts after Redis
6. **Celery Beat**: Starts after Redis and Django
7. **Nginx**: Can start independently

**Managed by systemd `Requires=` and `After=` directives in Quadlet files.**

## Resource Allocation Summary

### Phase 1: Single Server (8GB RAM)

| Service | Memory | CPU | Notes |
|---------|--------|-----|-------|
| PostgreSQL | 4GB | 2 cores | Database + buffer cache |
| Redis | 1GB | 1 core | All 4 databases |
| Django | 1.5GB | 1 core | ASGI server |
| Celery Worker | 2GB | 2 cores | Background tasks |
| Celery Beat | 512MB | 0.5 core | Scheduler |
| System | 1GB | - | OS, Nginx, etc. |
| **Total** | **10GB** | **6.5 cores** | **Exceeds 8GB! Tune down.** |

**Adjusted for 8GB server**:
- PostgreSQL: 2GB memory limit
- Redis: 512MB memory limit
- Django: 1GB memory limit
- Celery: 1.5GB memory limit
- Total: ~6.5GB (leaves room for system)

### Monitoring Resource Usage

```bash
# Container stats
podman stats --no-stream

# systemd resource accounting
systemctl --user status django.service | grep -i memory
systemctl --user status postgres.service | grep -i memory

# Overall system
free -h
htop
```

## Next Steps

1. **[Configure networking and SSL](./05-NETWORKING-SSL.md)**
2. **[Apply security hardening](./06-SECURITY-HARDENING.md)**
3. **[Set up monitoring](./07-MONITORING-LOGGING.md)**
4. **[Configure backups](./08-BACKUP-DISASTER-RECOVERY.md)**
