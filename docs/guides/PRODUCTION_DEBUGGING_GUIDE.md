# Production Debugging Guide

**Last Updated**: 2025-11-15
**Deployment Method**: Podman + Systemd (Quadlet)
**Architecture**: Rootless containers

This guide covers debugging a Senex Trader production deployment using Podman containers managed by systemd.

---

## Table of Contents

1. [Server Access](#server-access)
2. [Architecture Overview](#architecture-overview)
3. [Container Management](#container-management)
4. [Accessing Logs](#accessing-logs)
5. [Django Shell Commands](#django-shell-commands)
6. [Database Queries](#database-queries)
7. [Redis Cache Inspection](#redis-cache-inspection)
8. [File Locations](#file-locations)
9. [Deployment Process](#deployment-process)
10. [Common Debugging Scenarios](#common-debugging-scenarios)

---

## Server Access

### SSH Connection

```bash
# Connect to your production server
ssh root@your-server.example.com

# Switch to service user (default: senex)
su - senex
```

### User Details

| User | Purpose | Home Directory | Shell |
|------|---------|----------------|-------|
| `root` | System administration, deployment | `/root` | `/bin/bash` |
| `senex` | Service user running containers (customizable) | `/home/senex` | `/bin/bash` |

**Note**: The service username and paths are configurable during deployment via Ansible variables.

### Key Directories

Default paths (configurable via `app_directory` and `app_user` variables):

| Path | Purpose |
|------|---------|
| `/opt/senex-trader/` | Service configuration and quadlet files |
| `/opt/senex-trader/.config/containers/systemd/` | Quadlet container definitions |
| `/opt/senex-trader/.config/containers/systemd/.env` | Environment variables |
| `/home/senex/.local/share/containers/` | Podman storage |
| `/var/log/nginx/` | Nginx access/error logs (if using nginx) |

---

## Architecture Overview

### Container-Based Deployment (Podman + Quadlet)

Senex Trader runs as **rootless containers** managed by Podman and systemd (Quadlet).

```
┌─────────────────────────────────────────────────────────────┐
│                Production Server (Podman + Systemd)          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐  ┌───────────────┐  ┌────────────────────┐  │
│  │  Nginx   │→ │  web          │  │  celery_worker     │  │
│  │ (reverse │  │  (Daphne/     │  │  (background       │  │
│  │  proxy)  │  │   Django)     │  │   tasks)           │  │
│  │  :80/:443│  │  :8000        │  │                    │  │
│  └──────────┘  └───────────────┘  └────────────────────┘  │
│                         ↓                    ↓              │
│                  ┌─────────────────────────────┐            │
│                  │    senex_network            │            │
│                  │    (Podman bridge)          │            │
│                  └─────────────────────────────┘            │
│                         ↓                    ↓              │
│       ┌────────────────────┐      ┌────────────────────┐   │
│       │  postgres          │      │  redis             │   │
│       │  (PostgreSQL 15)   │      │  (Redis 7)         │   │
│       │  :5432             │      │  :6379             │   │
│       └────────────────────┘      └────────────────────┘   │
│                         ↓                    ↓              │
│                  ┌─────────────────────────────┐            │
│                  │  celery_beat                │            │
│                  │  (scheduler)                │            │
│                  └─────────────────────────────┘            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Services

| Service Name | Container Name | Purpose | Port |
|--------------|----------------|---------|------|
| `web.service` | `web` | Django/Daphne ASGI server | 8000 |
| `celery-worker.service` | `celery_worker` | Background task processor | - |
| `celery-beat.service` | `celery_beat` | Periodic task scheduler | - |
| `postgres.service` | `postgres` | PostgreSQL database | 5432 |
| `redis.service` | `redis` | Cache & message broker | 6379 |

### Network

- **Network**: `senex-network.network` (Podman bridge)
- **External Access**: Nginx proxies to `web:8000`
- **Internal**: Containers communicate via service names

---

## Container Management

### Podman Commands

All Podman commands run as `senex` user:

```bash
# Switch to senex user
su - senex

# List running containers
podman ps

# List all containers (including stopped)
podman ps -a

# Container status
podman ps --format "{{.Names}} {{.Status}}"
```

### Systemd Service Management

Services run as **user services** (not system services):

```bash
# As root - access senex user services
systemctl --user -M senex@ status SERVICE_NAME
systemctl --user -M senex@ restart SERVICE_NAME
systemctl --user -M senex@ stop SERVICE_NAME
systemctl --user -M senex@ start SERVICE_NAME

# Examples
systemctl --user -M senex@ status web.service
systemctl --user -M senex@ restart celery-worker.service
```

**Note**: `-M senex@` flag targets the senex user's systemd instance

### Container Lifecycle

#### Check Container Health

```bash
su - senex -c 'podman ps'
```

Expected output (container names and images will vary):
```
CONTAINER ID  IMAGE                                      COMMAND         STATUS
d1a88db92e0d  docker.io/library/postgres:15-alpine       postgres        Up 14 hours (healthy)
c3a1db0421b1  docker.io/library/redis:7-alpine          redis-server    Up 14 hours (healthy)
19d713ce799b  registry.example.com/org/senex-trader:v1.0  web            Up 14 hours
eb625528423d  registry.example.com/org/senex-trader:v1.0  celery-worker  Up 14 hours
7971dbd3111b  registry.example.com/org/senex-trader:v1.0  celery-beat    Up 14 hours
```

#### Restart Containers

```bash
# Restart via systemd (preferred - includes dependency handling)
systemctl --user -M senex@ restart web.service
systemctl --user -M senex@ restart celery-worker.service

# Restart container directly (alternative)
su - senex -c 'podman restart web'
```

#### Execute Commands in Containers

```bash
# Django shell
su - senex -c 'podman exec -i web python manage.py shell'

# Bash shell in container
su - senex -c 'podman exec -it web /bin/bash'

# One-off management command
su - senex -c 'podman exec web python manage.py check'
```

---

## Accessing Logs

### Journalctl (Recommended)

Containers log to **journald** via Podman's journald logging driver.

#### Basic Log Access

```bash
# View logs by container name
journalctl CONTAINER_NAME=celery_worker --no-pager

# Recent logs (last 100 lines)
journalctl CONTAINER_NAME=celery_worker -n 100 --no-pager

# Follow logs (tail -f equivalent)
journalctl CONTAINER_NAME=celery_worker -f

# Logs since specific time
journalctl CONTAINER_NAME=web --since "2025-11-05 10:00:00" --no-pager

# Logs between times
journalctl CONTAINER_NAME=celery_worker \
  --since "2025-11-05 14:00:00" \
  --until "2025-11-05 15:00:00" \
  --no-pager
```

#### Filtering Logs

```bash
# Search for keyword
journalctl CONTAINER_NAME=celery_worker --since today | grep "automated.*cycle"

# Multiple keywords (OR)
journalctl CONTAINER_NAME=web | grep -E "error|warning|critical"

# Case-insensitive search
journalctl CONTAINER_NAME=celery_worker | grep -i "negative credit"

# Context around match (5 lines before/after)
journalctl CONTAINER_NAME=celery_worker | grep -A 5 -B 5 "PRICING DIAGNOSTIC"
```

#### Common Log Queries

```bash
# All automated trade cycle runs today
journalctl CONTAINER_NAME=celery_worker --since today | grep "🤖 Starting automated"

# Errors only
journalctl CONTAINER_NAME=celery_worker --since today | grep "ERROR"

# Specific user's activity
journalctl CONTAINER_NAME=celery_worker --since today | grep "user@example.com"

# Negative credit detection
journalctl CONTAINER_NAME=celery_worker --since today | grep "INVALID PRICING"

# Order submissions
journalctl CONTAINER_NAME=celery_worker --since today | grep "ORDER PRICING BREAKDOWN"
```

### Podman Logs (Alternative)

```bash
# View container logs directly
su - senex -c 'podman logs celery_worker'

# Last 100 lines
su - senex -c 'podman logs celery_worker --tail 100'

# Follow logs
su - senex -c 'podman logs celery_worker -f'
```

**Note**: Podman logs may be empty if journald logging is enabled (which it is for Senex Trader). Use `journalctl` instead.

### Log Locations by Container

| Container | Log Method | Notes |
|-----------|------------|-------|
| `web` | `journalctl CONTAINER_NAME=web` | Django/Daphne logs |
| `celery_worker` | `journalctl CONTAINER_NAME=celery_worker` | Task execution logs |
| `celery_beat` | `journalctl CONTAINER_NAME=celery_beat` | Scheduler logs |
| `postgres` | `journalctl CONTAINER_NAME=postgres` | Database logs |
| `redis` | `journalctl CONTAINER_NAME=redis` | Cache logs |
| Nginx | `/var/log/nginx/access.log`, `/var/log/nginx/error.log` | HTTP access/errors |

---

## Django Shell Commands

### Accessing Django Shell

```bash
# Interactive Python shell with Django context
su - senex -c 'podman exec -i web python manage.py shell'
```

**Auto-imported objects**: Models, User, etc. (see shell startup messages)

### Running Shell Commands

#### Method 1: Interactive Shell

```bash
su - senex -c 'podman exec -it web python manage.py shell'
```

```python
# Inside shell
from trading.models import TradingSuggestion
s = TradingSuggestion.objects.latest('id')
print(f"Latest: {s.id} - {s.underlying_symbol}")
```

#### Method 2: Heredoc (One-liner)

```bash
su - senex -c 'podman exec -i web python manage.py shell' <<'PYEOF'
from trading.models import TradingSuggestion
s = TradingSuggestion.objects.latest('id')
print(f"Latest: {s.id} - {s.underlying_symbol}")
PYEOF
```

**Important**: Use single quotes for HEREDOC marker (`'PYEOF'`) to prevent variable expansion

#### Method 3: One-Line Command

```bash
su - senex -c 'podman exec web python manage.py shell -c "
from trading.models import TradingSuggestion;
print(TradingSuggestion.objects.count())
"'
```

### Common Django Shell Commands

#### Check Account Settings

```python
from accounts.models import TradingAccount

# Find automated accounts
accounts = TradingAccount.objects.filter(is_automated_trading_enabled=True)
for acc in accounts:
    print(f"{acc.user.email}: offset={acc.automated_entry_offset_cents}¢")
```

#### Check Today's Trades

```python
from trading.models import Trade
from django.utils import timezone

trades = Trade.objects.filter(
    submitted_at__date=timezone.now().date()
).exclude(status__in=["cancelled", "rejected", "expired"])

for trade in trades:
    print(f"{trade.user.email}: {trade.status} - ${trade.executed_price}")
```

#### Query Suggestions

```python
from trading.models import TradingSuggestion

# Latest suggestion
s = TradingSuggestion.objects.latest('id')
print(f"ID: {s.id}")
print(f"Symbol: {s.underlying_symbol}")
print(f"Natural Credit: {s.total_credit}")
print(f"Mid Credit: {s.total_mid_credit}")
print(f"Status: {s.status}")
```

#### Check Celery Task Results

```python
from django_celery_results.models import TaskResult
from django.utils import timezone

# Recent automated trade cycle tasks
tasks = TaskResult.objects.filter(
    task_name="trading.tasks.automated_daily_trade_cycle",
    date_created__date=timezone.now().date()
).order_by("-date_created")

for task in tasks[:5]:
    print(f"{task.date_created}: {task.status}")
    if task.result:
        print(f"  {task.result}")
```

---

## Database Queries

### Direct PostgreSQL Access

#### Via psql in Container

```bash
# Interactive psql session
su - senex -c 'podman exec -it postgres psql -U senextrader -d senextrader'

# One-off query
su - senex -c 'podman exec postgres psql -U senextrader -d senextrader -c "
SELECT COUNT(*) FROM trading_tradingsuggestion WHERE DATE(generated_at) = CURRENT_DATE;
"'
```

#### Common SQL Queries

##### Today's Trades

```sql
SELECT
    u.email,
    t.status,
    t.executed_price,
    t.submitted_at
FROM trading_trade t
JOIN auth_user u ON t.user_id = u.id
WHERE DATE(t.submitted_at) = CURRENT_DATE
ORDER BY t.submitted_at DESC;
```

##### Automated Accounts

```sql
SELECT
    u.email,
    ta.account_number,
    ta.automated_entry_offset_cents,
    ta.is_automated_trading_enabled
FROM accounts_tradingaccount ta
JOIN auth_user u ON ta.user_id = u.id
WHERE ta.is_automated_trading_enabled = true;
```

##### Recent Suggestions

```sql
SELECT
    id,
    underlying_symbol,
    total_credit,
    total_mid_credit,
    status,
    generated_at
FROM trading_tradingsuggestion
WHERE DATE(generated_at) = CURRENT_DATE
ORDER BY generated_at DESC
LIMIT 10;
```

### Database Connection Details

| Setting | Value |
|---------|-------|
| Host | `postgres` (container name) |
| Port | 5432 |
| Database | `senextrader` |
| User | `senextrader` |
| Password | (in `.env` file) |

### Backup & Restore

```bash
# Backup
su - senex -c 'podman exec postgres pg_dump -U senextrader senextrader > backup.sql'

# Restore
su - senex -c 'podman exec -i postgres psql -U senextrader senextrader < backup.sql'
```

---

## Redis Cache Inspection

### Accessing Redis CLI

```bash
# Interactive redis-cli
su - senex -c 'podman exec -it redis redis-cli'

# One-off command
su - senex -c 'podman exec redis redis-cli KEYS "*"'
```

### Redis Database Structure

| DB | Purpose |
|----|---------|
| 0 | Django cache |
| 1 | Channels (WebSocket) |
| 2 | Celery broker (task queue) |
| 3 | Celery results |

### Common Redis Commands

#### Select Database

```redis
SELECT 0   # Django cache
SELECT 1   # WebSocket
SELECT 2   # Celery broker
SELECT 3   # Celery results
```

#### Streaming Data Cache

```redis
# Select streaming database
SELECT 0

# Find option quote keys
KEYS quote:*

# Get specific quote
GET "quote:.QQQ251219P622"

# Find all QQQ option keys
KEYS "quote:*QQQ*"

# Check key TTL
TTL "quote:.QQQ251219P622"
```

#### Celery Tasks

```redis
# Select Celery broker database
SELECT 2

# Check pending tasks
KEYS celery-task-meta-*

# Get task result
GET "celery-task-meta-<task-id>"
```

#### Cache Statistics

```redis
# Get cache info
INFO

# Key count
DBSIZE

# Memory usage
INFO memory
```

### Clearing Cache

```bash
# Flush specific database
su - senex -c 'podman exec redis redis-cli -n 0 FLUSHDB'

# Flush all databases (DANGEROUS!)
su - senex -c 'podman exec redis redis-cli FLUSHALL'
```

---

## File Locations

### Production Directory Structure

```
/opt/senex-trader/
├── .config/
│   ├── containers/
│   │   └── systemd/
│   │       ├── .env                      # Environment variables
│   │       ├── celery-beat.container     # Quadlet: beat scheduler
│   │       ├── celery-worker.container   # Quadlet: worker
│   │       ├── web.container             # Quadlet: web/ASGI
│   │       ├── postgres.container        # Quadlet: database
│   │       ├── redis.container           # Quadlet: cache
│   │       └── senex-network.network     # Network definition
│   └── systemd/
│       └── user/
│           └── *.service.d/              # Service overrides
└── .local/
    └── share/
        └── containers/                   # Podman storage
```

### Application Code (Inside Containers)

```
/app/                                     # Container working directory
├── manage.py
├── senextrader/                         # Django project
│   ├── settings/
│   │   ├── base.py                       # Base settings
│   │   ├── production.py                 # Production settings
│   │   └── development.py                # Dev settings
│   └── celery.py                         # Celery config
├── trading/                              # Trading app
│   ├── tasks.py                          # Celery tasks
│   ├── models.py                         # Models
│   └── services/
│       └── automated_trading_service.py  # Automation logic
├── services/                             # Shared services
│   ├── streaming/
│   │   └── options_cache.py              # Pricing cache
│   └── execution/
│       └── order_service.py              # Order execution
├── accounts/                             # Accounts app
│   └── models.py                         # TradingAccount model
└── docker/
    └── entrypoint.sh                     # Container entrypoint
```

### Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| `.env` | `/opt/senex-trader/.config/containers/systemd/` | Environment variables |
| `base.py` | `/app/senextrader/settings/` | Django base settings |
| `production.py` | `/app/senextrader/settings/` | Production overrides |
| `celery.py` | `/app/senextrader/` | Celery configuration |

### Copying Files To/From Containers

```bash
# Copy file INTO container
su - senex -c 'podman cp /local/path/file.py web:/app/path/file.py'

# Copy file FROM container
su - senex -c 'podman cp web:/app/path/file.py /local/path/file.py'

# Copy then restart (apply changes)
su - senex -c 'podman cp file.py web:/app/file.py && podman restart web'
```

**Note**: Changes copied this way are **temporary** and lost on container rebuild. Use proper deployment for permanent changes.

---

## Deployment Process

### Overview

Deployment uses **Ansible** to:
1. Pull latest container image from Gitea registry
2. Update environment variables
3. Restart services
4. Run database migrations

### Manual Deployment Steps

#### 1. Build & Push Image (Local)

```bash
# From project root on development machine
make build TAG=v1.0.0

# Or use build script directly
./build.py --tag v1.0.0
```

This builds the container image and pushes to your configured registry.

#### 2. Deploy to Production

```bash
# From deployment directory
cd deployment/ansible
make deploy-production
```

This runs the Ansible playbook which:
- Pulls new image
- Restarts containers
- Runs migrations
- Collects static files

### Manual Container Update (Advanced)

```bash
# SSH to production
ssh root@your-server.example.com

# Pull new image (update registry URL and tag)
su - senex -c 'podman pull registry.example.com/org/senex-trader:v1.0.0'

# Update .env with new tag
vim /opt/senex-trader/.config/containers/systemd/.env
# Set: IMAGE_TAG=v1.0.0

# Restart services
systemctl --user -M senex@ restart web.service
systemctl --user -M senex@ restart celery-worker.service
systemctl --user -M senex@ restart celery-beat.service

# Run migrations
su - senex -c 'podman exec web python manage.py migrate'
```

### Hot-Patching Files (Emergency Only)

**Use case**: Critical bug fix needed immediately, can't wait for full deployment

```bash
# 1. Copy fixed file to server
scp fixed_file.py root@your-server.example.com:/tmp/

# 2. Copy into container
su - senex -c 'podman cp /tmp/fixed_file.py web:/app/path/to/fixed_file.py'
su - senex -c 'podman cp /tmp/fixed_file.py celery_worker:/app/path/to/fixed_file.py'

# 3. Restart services
systemctl --user -M senex@ restart celery-worker.service

# 4. Verify
journalctl CONTAINER_NAME=celery_worker -n 50
```

**Important**: Hot-patches are **temporary** and lost on container rebuild. Follow up with proper deployment!

---

## Common Debugging Scenarios

### Scenario 1: Automated Trade Cycle Failed

#### Symptoms
- No trades executed today
- Logs show errors
- Email notifications not received

#### Investigation Steps

```bash
# 1. Check if task ran
journalctl CONTAINER_NAME=celery_worker --since today | grep "automated.*cycle"

# 2. Check for errors
journalctl CONTAINER_NAME=celery_worker --since today | grep -i "error\|failed"

# 3. Check specific user
journalctl CONTAINER_NAME=celery_worker --since today | grep "user@example.com"

# 4. Verify account settings
su - senex -c 'podman exec -i web python manage.py shell' <<'PYEOF'
from accounts.models import TradingAccount
acc = TradingAccount.objects.get(account_number="ABC12345")
print(f"Enabled: {acc.is_automated_trading_enabled}")
print(f"Token Valid: {acc.is_token_valid}")
print(f"Offset: {acc.automated_entry_offset_cents}¢")
PYEOF

# 5. Check for existing trade today
su - senex -c 'podman exec -i web python manage.py shell' <<'PYEOF'
from trading.models import Trade
from django.utils import timezone
trades = Trade.objects.filter(
    submitted_at__date=timezone.now().date()
).exclude(status__in=["cancelled", "rejected", "expired"])
print(f"Trades today: {trades.count()}")
PYEOF
```

### Scenario 2: Negative Credit Detection

#### Symptoms
- Logs show "INVALID PRICING DETECTED"
- Suggestion generation fails
- Retry attempts exhausted

#### Investigation Steps

```bash
# 1. Find negative credit errors
journalctl CONTAINER_NAME=celery_worker --since today | grep "INVALID PRICING" | head -20

# 2. Check for diagnostic details
journalctl CONTAINER_NAME=celery_worker --since today | grep -A 20 "PRICING DIAGNOSTIC"

# 3. Verify suggestion data
su - senex -c 'podman exec -i web python manage.py shell' <<'PYEOF'
from trading.models import TradingSuggestion
s = TradingSuggestion.objects.latest('id')
print(f"ID: {s.id}")
print(f"Natural Credit: {s.total_credit}")
print(f"Mid Credit: {s.total_mid_credit}")
print(f"Put Credit: {s.put_spread_credit}")
print(f"Call Credit: {s.call_spread_credit}")
PYEOF

# 4. Check Redis cache
su - senex -c 'podman exec redis redis-cli -c "
SELECT 0
KEYS quote:*QQQ*
"'
```

#### Resolution

- **If data is stale**: Wait for next 15-minute run
- **If persistent**: Check DXFeed connection in web UI
- **If widespread**: May need to flush Redis cache

### Scenario 3: Container Won't Start

#### Symptoms
- `podman ps` shows container missing
- Service status shows "failed"
- Application not responding

#### Investigation Steps

```bash
# 1. Check service status
systemctl --user -M senex@ status web.service

# 2. Check container logs
su - senex -c 'podman logs web --tail 100'

# 3. Try manual start
su - senex -c 'podman start web'

# 4. Check for port conflicts
su - senex -c 'podman port web'
netstat -tulpn | grep 8000

# 5. Inspect container config
su - senex -c 'podman inspect web'
```

#### Resolution

```bash
# Restart service
systemctl --user -M senex@ restart web.service

# If still failing, recreate container
systemctl --user -M senex@ stop web.service
su - senex -c 'podman rm -f web'
systemctl --user -M senex@ start web.service
```

### Scenario 4: Database Connection Issues

#### Symptoms
- "connection refused" errors
- "database unavailable"
- Django can't connect

#### Investigation Steps

```bash
# 1. Check postgres container
su - senex -c 'podman ps | grep postgres'

# 2. Test database connection
su - senex -c 'podman exec postgres pg_isready -U senextrader'

# 3. Check connections
su - senex -c 'podman exec postgres psql -U senextrader -d senextrader -c "
SELECT count(*) FROM pg_stat_activity;
"'

# 4. Check network
su - senex -c 'podman network inspect senex-network'
```

#### Resolution

```bash
# Restart postgres
systemctl --user -M senex@ restart postgres.service

# Restart dependent services
systemctl --user -M senex@ restart web.service
systemctl --user -M senex@ restart celery-worker.service
```

### Scenario 5: High Memory/CPU Usage

#### Symptoms
- Server slow/unresponsive
- OOM killer messages
- High load average

#### Investigation Steps

```bash
# 1. Check system resources
top
htop
free -h

# 2. Container resource usage
su - senex -c 'podman stats --no-stream'

# 3. Find resource hog
su - senex -c 'podman stats'

# 4. Check for memory leaks
su - senex -c 'podman exec web python manage.py check'
```

#### Resolution

```bash
# Restart problematic container
systemctl --user -M senex@ restart celery-worker.service

# If severe, restart all
systemctl --user -M senex@ restart *.service
```

---

## Quick Reference

### Most Used Commands

```bash
# Logs
journalctl CONTAINER_NAME=celery_worker --since today | grep "automated"

# Django shell
su - senex -c 'podman exec -i web python manage.py shell'

# Container status
su - senex -c 'podman ps'

# Restart service
systemctl --user -M senex@ restart celery-worker.service

# Check recent trades
# (use Django shell heredoc from examples above)
```

### Emergency Contacts

| Issue | Action |
|-------|--------|
| Site down | Check nginx, restart web.service |
| Trades failing | Check logs, verify TastyTrade API |
| Database issues | Check postgres container, restart if needed |
| Out of disk | Clean up old containers/images |

---

## Related Documentation

- [DEPLOYMENT-DEBUGGING-GUIDE.md](../../docs/deployment/DEPLOYMENT-DEBUGGING-GUIDE.md) - Comprehensive deployment guide
- [AUTOMATED_DAILY_TRADING_CYCLE.md](AUTOMATED_DAILY_TRADING_CYCLE.md) - Automation workflow
- [TASTYTRADE_SDK_BEST_PRACTICES.md](TASTYTRADE_SDK_BEST_PRACTICES.md) - API integration
- [REALTIME_DATA_FLOW_PATTERN.md](../patterns/REALTIME_DATA_FLOW_PATTERN.md) - Streaming architecture

---

## Tips & Best Practices

### 1. Always Use Journalctl for Logs

**Do**: `journalctl CONTAINER_NAME=web`
**Don't**: `podman logs web` (often empty)

### 2. Prefer Systemd for Service Management

**Do**: `systemctl --user -M senex@ restart web.service`
**Don't**: `podman restart web` (skips dependency handling)

### 3. Use Heredocs for Django Shell

**Do**: `podman exec -i web python manage.py shell` with heredoc
**Don't**: `podman exec web python -c "..."` (quoting hell)

### 4. Check Logs by Container Name, Not Service

**Do**: `journalctl CONTAINER_NAME=celery_worker`
**Don't**: `journalctl -u celery-worker.service` (may not work)

### 5. Deploy Properly, Hot-Patch Only in Emergencies

**Do**: Build image, run Ansible deployment
**Don't**: Copy files directly into containers (not persistent)

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-05 | 1.0 | Initial production debugging guide |
