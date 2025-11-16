# Senex Trader Container Architecture

## Overview

Senex Trader requires a multi-container architecture with five services orchestrated to provide a complete automated trading platform. This document defines the container architecture, service dependencies, networking, and persistence strategy.

---

## Container Services

### Service 1: PostgreSQL Database (`postgres`)

**Purpose**: Primary data persistence for all application data

**Image**: `postgres:16-alpine`

**Exposed Ports**:
- `5432` (internal only - do not expose publicly)

**Volumes**:
- `postgres_data:/var/lib/postgresql/data` (persistent storage)

**Environment Variables**:
- `POSTGRES_DB=senex_trader`
- `POSTGRES_USER=senex_user`
- `POSTGRES_PASSWORD=${DB_PASSWORD}` (from secret)

**Health Check**:
```bash
pg_isready -U senex_user -d senex_trader
```

**Resource Recommendations**:
- Memory: 2-4 GB
- CPU: 1-2 cores

---

### Service 2: Redis Cache/Broker (`redis`)

**Purpose**: Cache layer, Celery message broker, Channels WebSocket backend

**Image**: `redis:7-alpine`

**Exposed Ports**:
- `6379` (internal only - do not expose publicly)

**Volumes**:
- `redis_data:/data` (optional - for AOF persistence)

**Command**:
```bash
redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
```

**Redis Database Allocation**:
- **DB 0**: Django cache (production)
- **DB 1**: Django cache (development)
- **DB 2**: Celery broker
- **DB 3**: Celery result backend

**Health Check**:
```bash
redis-cli ping
```

**Resource Recommendations**:
- Memory: 512 MB - 1 GB
- CPU: 0.5-1 core

---

### Service 3: Django Web Application (`web`)

**Purpose**: HTTP/WebSocket server for user interface and API

**Image**: `senex_trader:latest` (custom build)

**Exposed Ports**:
- `8000:8000` (HTTP/WebSocket - behind reverse proxy in production)

**Volumes**:
- `logs:/var/log/senex_trader` (application logs)
- `staticfiles:/app/staticfiles` (optional - collected static files)

**Command**:
```bash
daphne -b 0.0.0.0 -p 8000 senex_trader.asgi:application
```

**Dependencies**:
- Requires `postgres` (healthy)
- Requires `redis` (healthy)

**Health Check**:
```bash
curl -f http://localhost:8000/health/ || exit 1
```

**Environment Variables**: See `environment-variables.md`

**Resource Recommendations**:
- Memory: 512 MB - 1 GB
- CPU: 0.5-1 core per instance

**Scaling**: Can run multiple replicas with load balancer

---

### Service 4: Celery Worker (`celery_worker`)

**Purpose**: Background task execution (order monitoring, position sync, reconciliation)

**Image**: `senex_trader:latest` (same as web)

**Exposed Ports**: None

**Volumes**:
- `logs:/var/log/senex_trader` (application logs)

**Command**:
```bash
celery -A senex_trader worker \
  --loglevel=info \
  --queues=celery,accounts,trading \
  --concurrency=4 \
  --max-tasks-per-child=100
```

**Dependencies**:
- Requires `postgres` (healthy)
- Requires `redis` (healthy)

**Health Check**:
```bash
celery -A senex_trader inspect ping -d celery@$HOSTNAME
```

**Environment Variables**: See `environment-variables.md`

**Resource Recommendations**:
- Memory: 1-2 GB
- CPU: 1-2 cores

**Scaling**: Can run multiple replicas for increased throughput

**Task Queues**:
- `celery` - Default queue for general tasks
- `accounts` - Account-related operations
- `trading` - High-priority trading operations

---

### Service 5: Celery Beat Scheduler (`celery_beat`)

**Purpose**: Schedule periodic tasks (position sync, reconciliation, trading cycles)

**Image**: `senex_trader:latest` (same as web)

**Exposed Ports**: None

**Volumes**:
- `logs:/var/log/senex_trader` (application logs)
- `celerybeat_schedule:/app` (scheduler state persistence)

**Command**:
```bash
celery -A senex_trader beat \
  --loglevel=info \
  --pidfile=/tmp/celerybeat.pid \
  --schedule=/app/celerybeat-schedule
```

**Dependencies**:
- Requires `postgres` (healthy)
- Requires `redis` (healthy)

**Health Check**: Not applicable (scheduler process)

**Environment Variables**: See `environment-variables.md`

**Resource Recommendations**:
- Memory: 256-512 MB
- CPU: 0.25-0.5 core

**Scaling**: **MUST run only 1 instance** (single scheduler to avoid duplicate tasks)

**Scheduled Tasks** (executed by Celery Beat):
- `monitor_open_orders` - Every 5 minutes
- `sync_positions_task` - Every 10 minutes
- `sync_order_history_task` - Every 15 minutes
- `reconcile_trades_with_tastytrade` - Every 30 minutes
- `automated_daily_trade_cycle` - 10:00 AM ET weekdays
- `monitor_positions_for_dte_closure` - 9:30 AM ET daily
- `generate_trading_summary` - 4:30 PM ET weekdays
- `cleanup_inactive_streamers` - Every hour
- `cleanup_cancelled_trades` - 3:00 AM ET daily
- `cleanup_old_suggestions` - 3:30 AM ET daily

---

## Service Dependency Graph

```
┌────────────────────────────────────────────────────────────────┐
│                         External Services                        │
│  • TastyTrade API (api.tastyworks.com)                          │
│  • TastyTrade DXLink Streaming (WebSocket)                      │
└────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ HTTPS/WebSocket
                                  │
┌─────────────────────────────────┼─────────────────────────────────┐
│                                 │                                 │
│  ┌──────────────────────────────┴───────────────────────┐        │
│  │              PostgreSQL Database (postgres)          │        │
│  │                   Port: 5432 (internal)              │        │
│  │            Volume: postgres_data (persistent)        │        │
│  └──────────────────────────┬───────────────────────────┘        │
│                             │                                     │
│  ┌──────────────────────────┴───────────────────────┐            │
│  │           Redis Cache/Broker (redis)             │            │
│  │              Port: 6379 (internal)               │            │
│  │          Volume: redis_data (optional)           │            │
│  └──────────────────────────┬───────────────────────┘            │
│                             │                                     │
│         ┌───────────────────┼───────────────────┐                │
│         │                   │                   │                │
│  ┌──────▼──────┐   ┌────────▼────────┐   ┌─────▼──────────┐     │
│  │ Django Web  │   │ Celery Worker   │   │  Celery Beat   │     │
│  │   (web)     │   │ (celery_worker) │   │ (celery_beat)  │     │
│  │ Port: 8000  │   │  Multi-replica  │   │ Single instance│     │
│  │ Multi-      │   │                 │   │                │     │
│  │ replica     │   │                 │   │                │     │
│  └─────────────┘   └─────────────────┘   └────────────────┘     │
│         │                                                         │
│         │ HTTP/WebSocket                                         │
│         ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │          Reverse Proxy (Nginx/Traefik/ALB)              │    │
│  │                   Ports: 80, 443                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│         │                                                         │
└─────────┼─────────────────────────────────────────────────────────┘
          │
          ▼
     End Users
```

---

## Container Startup Sequence

### Phase 1: Data Layer (Start First)
1. **PostgreSQL** starts and initializes
   - Wait for `pg_isready` health check
   - Database ready for connections

2. **Redis** starts and initializes
   - Wait for `redis-cli ping` health check
   - Cache/broker ready

### Phase 2: Application Layer (Start After Data Layer)
3. **Django Web** starts
   - Wait for PostgreSQL + Redis healthy
   - Run database migrations (`python manage.py migrate`)
   - Collect static files (`python manage.py collectstatic --noinput`)
   - Start Daphne ASGI server
   - Listen on port 8000

4. **Celery Worker** starts (can start in parallel with web)
   - Wait for PostgreSQL + Redis healthy
   - Connect to Redis broker (DB 2)
   - Register task queues: `celery`, `accounts`, `trading`
   - Begin processing tasks

5. **Celery Beat** starts (can start in parallel with web/worker)
   - Wait for PostgreSQL + Redis healthy
   - Load schedule from database (django-celery-beat)
   - Begin dispatching periodic tasks

### Phase 3: Traffic Layer (Optional - Production Only)
6. **Reverse Proxy** starts
   - Wait for Django Web healthy
   - Route HTTP/HTTPS traffic to web containers
   - Handle SSL termination
   - Serve static files (optional)

---

## Network Configuration

### Internal Network (`senex_network`)

**Type**: Bridge network (Docker/Podman)

**Service Communication**:
- All services communicate via internal DNS names
- Service names resolve to container IPs
- No external exposure for data layer

**DNS Resolution**:
- `postgres` → PostgreSQL container IP
- `redis` → Redis container IP
- `web` → Django web container IP(s)
- `celery_worker` → Celery worker container IP(s)
- `celery_beat` → Celery beat container IP

**Network Isolation**:
- Data layer (postgres, redis) not accessible from host (no port mapping)
- Application layer (web) exposes only port 8000 for HTTP/WebSocket
- Worker/Beat have no exposed ports

### Port Mapping

| Service | Internal Port | External Port | Public Access |
|---------|---------------|---------------|---------------|
| PostgreSQL | 5432 | - | No (internal only) |
| Redis | 6379 | - | No (internal only) |
| Django Web | 8000 | 8000 (dev) / - (prod) | No (behind proxy) |
| Celery Worker | - | - | No |
| Celery Beat | - | - | No |
| Reverse Proxy | 80, 443 | 80, 443 | Yes |

**Development**: Expose Django Web port 8000 directly for testing
**Production**: Route all traffic through reverse proxy (no direct web exposure)

---

## Volume Persistence Strategy

### Volume 1: PostgreSQL Data (`postgres_data`)

**Type**: Named volume (persistent)

**Mount Point**: `/var/lib/postgresql/data`

**Purpose**: All database tables, indexes, and transaction logs

**Backup Strategy**:
- Use `pg_dump` to create logical backups
- Mount backup directory for automated dumps
- Consider WAL archiving for point-in-time recovery

**Size**: Start with 10 GB, monitor growth

---

### Volume 2: Redis Data (`redis_data`)

**Type**: Named volume (optional - can be ephemeral)

**Mount Point**: `/data`

**Purpose**: AOF/RDB persistence (optional)

**Configuration**:
- **Ephemeral**: Remove volume, accept data loss on restart
- **Persistent**: Use AOF (`appendonly yes`) for durability

**Recommendation**: Ephemeral for cache-only usage (broker messages are transient)

---

### Volume 3: Application Logs (`logs`)

**Type**: Named volume

**Mount Point**: `/var/log/senex_trader`

**Purpose**: Structured application logs from all services

**Log Files**:
- `application.log` - General application logs (50 MB, 10 backups)
- `errors.log` - Error-level logs (50 MB, 10 backups)
- `trading.log` - Trading-specific logs (100 MB, 20 backups)
- `security.log` - Security events (50 MB, 10 backups)

**Log Rotation**: Automatic via Python's RotatingFileHandler

**Alternative**: Use stdout/stderr logging with external log aggregator (ELK, CloudWatch)

---

### Volume 4: Celery Beat Schedule (`celerybeat_schedule`)

**Type**: Named volume (optional - can recreate from database)

**Mount Point**: `/app` (contains `celerybeat-schedule*` files)

**Purpose**: SQLite-based scheduler state

**Files**:
- `celerybeat-schedule` - Main schedule database
- `celerybeat-schedule-shm` - Shared memory
- `celerybeat-schedule-wal` - Write-ahead log

**Note**: Schedule is also stored in PostgreSQL (django-celery-beat), so volume persistence is optional

---

### Volume 5: Static Files (`staticfiles`)

**Type**: Named volume (optional - build artifact)

**Mount Point**: `/app/staticfiles`

**Purpose**: Collected Django static files

**Build Step**: `python manage.py collectstatic --noinput`

**Serving Strategy**:
- **WhiteNoise**: Serve from Django (no volume needed)
- **Nginx**: Share volume between Django (writer) and Nginx (reader)

**Recommendation**: Use WhiteNoise (simpler, no separate static file server needed)

---

## Container Communication Patterns

### Database Connections

**Django Web → PostgreSQL**:
- Connection pool (CONN_MAX_AGE=600 seconds)
- SSL required in production (`sslmode=require`)
- Connection string: `postgresql://senex_user:${DB_PASSWORD}@postgres:5432/senex_trader`

**Celery Worker → PostgreSQL**:
- Same connection pool settings as web
- Accesses database for task state and results

**Celery Beat → PostgreSQL**:
- Reads schedule from `django_celery_beat` tables
- Lightweight connection (scheduler only)

### Redis Connections

**Django Web → Redis**:
- Cache backend: `redis://redis:6379/0`
- Channels backend: `redis://redis:6379/0`
- Session storage: `redis://redis:6379/0`

**Celery Worker → Redis**:
- Broker: `redis://redis:6379/2`
- Result backend: `redis://redis:6379/3`

**Celery Beat → Redis**:
- Broker: `redis://redis:6379/2`

### WebSocket Connections

**Browser → Django Web**:
- WebSocket upgrade over HTTP
- Channels routing: `ws://web:8000/ws/streaming/`
- Authenticated via Django session

**Django Web → Redis (Channels)**:
- Channels layer for WebSocket message passing
- Pub/sub for real-time updates across multiple web instances

### External API Connections

**All Services → TastyTrade API**:
- HTTPS: `https://api.tastyworks.com` (production)
- HTTPS: `https://api.cert.tastyworks.com` (sandbox)
- OAuth 2.0 authentication
- Session refresh every 15 minutes
- Outbound connections only (no inbound requirements)

**Django Web → TastyTrade DXLink**:
- WebSocket streaming for market data
- Subscription-based (only when users request streaming)
- Managed by StreamManager service

---

## Security Considerations

### Network Security

1. **Internal Network Isolation**: Data layer (postgres, redis) not exposed to host
2. **Minimal Port Exposure**: Only reverse proxy ports (80, 443) publicly accessible
3. **Service-to-Service TLS**: PostgreSQL SSL connections enforced
4. **No Root Privileges**: All containers run as non-root user (UID 1000)

### Secret Management

1. **Environment Variables**: Inject secrets via compose/orchestrator
2. **No Hardcoded Secrets**: All secrets from external sources
3. **Encrypted Storage**: Sensitive data (OAuth tokens) encrypted in database

### Access Control

1. **Database Access**: Only application services can connect
2. **Redis Access**: No authentication required (internal network only)
3. **Admin Interface**: Accessible only through web service (authenticated)

---

## Scaling Strategy

### Horizontal Scaling (Multiple Replicas)

**Services That Can Scale**:
- ✅ **Django Web**: Multiple replicas with load balancer
- ✅ **Celery Worker**: Multiple replicas for increased throughput

**Services That Cannot Scale**:
- ❌ **Celery Beat**: Single instance only (scheduler conflict)
- ❌ **PostgreSQL**: Requires replication setup (primary/replica)
- ❌ **Redis**: Requires cluster setup (Redis Cluster)

### Load Balancing

**Django Web**:
- Reverse proxy distributes HTTP requests across replicas
- Session affinity not required (Redis session backend)
- WebSocket connections use sticky sessions (optional)

**Celery Worker**:
- Redis broker distributes tasks across workers
- Workers pull tasks from queues (fair distribution)
- Task routing by queue name (`celery`, `accounts`, `trading`)

### Resource Scaling

**Vertical Scaling** (increase container resources):
- Increase memory/CPU for single containers
- Useful for CPU-intensive tasks (data analysis, backtesting)

**Horizontal Scaling** (add more containers):
- Add more web replicas for increased user concurrency
- Add more worker replicas for increased task throughput

---

## Monitoring & Observability

### Health Checks

**PostgreSQL**:
```bash
pg_isready -U senex_user -d senex_trader
```

**Redis**:
```bash
redis-cli ping
```

**Django Web**:
```bash
curl -f http://localhost:8000/health/ || exit 1
```

**Celery Worker**:
```bash
celery -A senex_trader inspect ping -d celery@$HOSTNAME
```

### Logging

**Log Aggregation**:
- All services log to `logs` volume
- Structured format with timestamp, level, service, message
- Centralized log collection recommended (ELK, Splunk, CloudWatch)

**Log Levels**:
- Development: DEBUG
- Production: INFO (application), WARNING (root)

### Metrics (Future Enhancement)

**Application Metrics**:
- Request rate, response time (web)
- Task rate, task duration (celery)
- Queue depth (redis)

**Infrastructure Metrics**:
- CPU, memory, disk usage (containers)
- Network throughput (inter-container)
- Connection pool utilization (database)

---

## Disaster Recovery

### Backup Strategy

**PostgreSQL**:
- Daily full backup via `pg_dump`
- Continuous WAL archiving for point-in-time recovery
- Store backups in external storage (S3, GCS, Azure Blob)

**Redis**:
- Optional RDB snapshots if persistence enabled
- Not critical (cache can be rebuilt)

**Application Logs**:
- Ship logs to external storage
- Retain 90 days for compliance

### Recovery Procedures

**Database Failure**:
1. Stop all application services
2. Restore PostgreSQL from latest backup
3. Replay WAL logs if available
4. Start application services
5. Verify data integrity

**Application Service Failure**:
1. Container orchestrator auto-restarts failed containers
2. No data loss (stateless containers)
3. Health checks detect failures and route traffic to healthy instances

**Complete System Failure**:
1. Provision new infrastructure
2. Restore PostgreSQL from backup
3. Deploy containers from registry
4. Update DNS to new infrastructure
5. Verify all services healthy

---

## Summary

The Senex Trader container architecture provides:

- ✅ **5 Services**: Django Web (ASGI), Celery Worker, Celery Beat, PostgreSQL, Redis
- ✅ **Stateless Application Tier**: Web, Worker, Beat can scale horizontally
- ✅ **Persistent Data Tier**: PostgreSQL with backup/recovery strategy
- ✅ **Internal Network Isolation**: Data layer not exposed to host
- ✅ **Health Checks**: All services monitored for availability
- ✅ **Log Aggregation**: Centralized logging for troubleshooting
- ✅ **Horizontal Scaling**: Multiple web/worker replicas supported
- ✅ **Security**: Non-root containers, SSL enforcement, secret management

**Next Steps**: See `dockerfile-design.md` for container image design and `docker-compose-strategy.md` for orchestration configuration.
