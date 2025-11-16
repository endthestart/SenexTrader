# Scaling Strategy

## Scaling Decision Matrix

| Metric | Threshold | Action | Priority |
|--------|-----------|--------|----------|
| Django CPU | >70% (5 min) | Add Django instance | High |
| PostgreSQL CPU | >80% (10 min) | Add read replica | High |
| Redis Memory | >90% | Upgrade instance or add Sentinel | Critical |
| Celery Queue | >100 tasks (5 min) | Add worker | Medium |
| WebSocket Conn | >1500/instance | Add Daphne instance | Medium |
| Disk Usage | >80% | Expand storage or archive data | High |

## Horizontal Scaling: Django/Daphne

### Add Django Instance

**1. Update Quadlet file** (instance-based):

```bash
# Create second instance
cp ~/.config/containers/systemd/django.container \
   ~/.config/containers/systemd/django@.container
```

**django@.container** (template):
```ini
[Unit]
Description=Django/Daphne Instance %i
After=postgres.service redis.service
Requires=postgres.service redis.service

[Container]
Image=registry.example.com/senex-trader:latest
ContainerName=django-%i
Network=senex_net.network

# Different port for each instance
PublishPort=800%i:8000

# Shared environment and volumes
EnvironmentFile=/etc/senex-trader/.env
Volume=%h/senex-trader/static:/app/staticfiles:z
Volume=%h/senex-trader/media:/app/media:z

HealthCmd=curl -f http://localhost:8000/health/ || exit 1
HealthInterval=30s

Memory=1536M
CPUQuota=100%

Exec=daphne -b 0.0.0.0 -p 8000 --access-log - senextrader.asgi:application

[Service]
Restart=always

[Install]
WantedBy=default.target
```

**2. Enable instances**:

```bash
# Reload systemd
systemctl --user daemon-reload

# Start instances
systemctl --user enable --now django@1.service
systemctl --user enable --now django@2.service
systemctl --user enable --now django@3.service

# Verify
podman ps | grep django
# Should show: django-1, django-2, django-3
```

**3. Update Nginx upstream**:

```nginx
upstream django_backend {
    # Use ip_hash for sticky sessions
    ip_hash;
    
    server 127.0.0.1:8001 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:8002 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:8003 max_fails=3 fail_timeout=30s;
    
    keepalive 32;
}
```

**4. Reload Nginx**:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

**5. Verify load distribution**:

```bash
# Monitor access logs
sudo tail -f /var/log/nginx/access.log | grep -oP '127\.0\.0\.\d:\d+'

# Should show requests distributed across 8001, 8002, 8003
```

## Database Scaling

### PgBouncer Connection Pooling

**Installation**:

```bash
sudo apt install pgbouncer
```

**Configuration** (`/etc/pgbouncer/pgbouncer.ini`):

```ini
[databases]
senextrader = host=localhost port=5432 dbname=senextrader user=senex_user

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432

# Authentication
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

# CRITICAL: Transaction pooling for Django
pool_mode = transaction

# Connection limits
max_client_conn = 200        # Django + Celery connections
default_pool_size = 25       # Actual PostgreSQL connections
reserve_pool_size = 5
reserve_pool_timeout = 3

# Server settings
server_idle_timeout = 600
server_lifetime = 3600
server_login_retry = 15

# Client settings
client_login_timeout = 60

# Logging
log_connections = 1
log_disconnections = 1
log_pooler_errors = 1
logfile = /var/log/postgresql/pgbouncer.log
pidfile = /var/run/postgresql/pgbouncer.pid

# Admin
admin_users = postgres
stats_users = postgres
```

**User list** (`/etc/pgbouncer/userlist.txt`):

```bash
# Generate MD5 hash
echo -n "passwordsenex_user" | md5sum
# Output: abc123...

# Add to userlist.txt
echo '"senex_user" "md5abc123..."' | sudo tee /etc/pgbouncer/userlist.txt
```

**Django Configuration**:

```python
# settings/production.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'PORT': '6432',  # PgBouncer port
        'CONN_MAX_AGE': None,  # Let PgBouncer manage connections
        'DISABLE_SERVER_SIDE_CURSORS': True,  # Required for transaction mode
    }
}
```

**Start PgBouncer**:

```bash
sudo systemctl enable pgbouncer
sudo systemctl start pgbouncer

# Test connection
psql -h localhost -p 6432 -U senex_user senextrader
```

**Monitor PgBouncer**:

```bash
# Connect to admin console
psql -h localhost -p 6432 -U postgres pgbouncer

# View pools
SHOW POOLS;

# View clients
SHOW CLIENTS;

# View servers
SHOW SERVERS;

# View stats
SHOW STATS;
```

### PostgreSQL Read Replica

**Setup on replica server**:

**1. Configure primary for replication**:

```sql
-- On primary PostgreSQL
ALTER SYSTEM SET wal_level = replica;
ALTER SYSTEM SET max_wal_senders = 5;
ALTER SYSTEM SET wal_keep_size = '1GB';

-- Restart PostgreSQL
SELECT pg_reload_conf();

-- Create replication user
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'STRONG_PASSWORD';
```

**pg_hba.conf** (on primary):

```
# TYPE  DATABASE    USER        ADDRESS         METHOD
host    replication replicator  REPLICA_IP/32   md5
```

**2. Create base backup on replica**:

```bash
# On replica server
pg_basebackup -h PRIMARY_IP -U replicator -D /var/lib/postgresql/data -P -R
```

**3. Start replica**:

```bash
# On replica
systemctl start postgresql

# Verify replication
psql -U postgres -c "SELECT pg_is_in_recovery();"
# Should return: t (true)

# Check replication lag
psql -U postgres -c "SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;"
```

**4. Django database router**:

```python
# senextrader/db_router.py
class ReplicaRouter:
    def db_for_read(self, model, **hints):
        """Route reads to replica"""
        return "replica"
    
    def db_for_write(self, model, **hints):
        """Route writes to primary"""
        return "default"
    
    def allow_relation(self, obj1, obj2, **hints):
        return True
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Only migrate on primary"""
        return db == "default"

# settings/production.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': 'primary-db.internal',
        'PORT': '6432',  # PgBouncer
    },
    'replica': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': 'replica-db.internal',
        'PORT': '6432',
    }
}

DATABASE_ROUTERS = ['senextrader.db_router.ReplicaRouter']
```

## Redis Scaling

### Redis Sentinel (High Availability)

**Architecture**:
```
Redis Primary (read/write)
├── Redis Replica 1 (read-only)
└── Redis Replica 2 (read-only)

Sentinel 1, 2, 3 (quorum-based failover)
```

**Redis configuration** (primary):

```conf
# redis-primary.conf
port 6379
requirepass STRONG_PASSWORD
masterauth STRONG_PASSWORD

# Replication
replicaof no one  # This is the primary
```

**Redis configuration** (replicas):

```conf
# redis-replica.conf
port 6379
requirepass STRONG_PASSWORD
masterauth STRONG_PASSWORD

# Replication
replicaof PRIMARY_IP 6379
replica-read-only yes
```

**Sentinel configuration** (all sentinels):

```conf
# sentinel.conf
port 26379

# Monitor primary
sentinel monitor senex-redis PRIMARY_IP 6379 2  # Quorum of 2
sentinel auth-pass senex-redis STRONG_PASSWORD

# Failover settings
sentinel down-after-milliseconds senex-redis 5000
sentinel parallel-syncs senex-redis 1
sentinel failover-timeout senex-redis 10000
```

**Start Sentinel**:

```bash
redis-sentinel /etc/redis/sentinel.conf
```

**Django configuration with Sentinel**:

```python
# Install: pip install django-redis

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://senex-redis/0",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.SentinelClient",
            "SENTINELS": [
                ("sentinel-1", 26379),
                ("sentinel-2", 26379),
                ("sentinel-3", 26379),
            ],
            "SENTINEL_KWARGS": {"password": "SENTINEL_PASSWORD"},
            "PASSWORD": "REDIS_PASSWORD",
            "CONNECTION_POOL_KWARGS": {"max_connections": 50},
        },
    }
}

CELERY_BROKER_URL = "sentinel://sentinel-1:26379;sentinel-2:26379;sentinel-3:26379"
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "master_name": "senex-redis",
    "sentinel_kwargs": {"password": "SENTINEL_PASSWORD"},
}
```

## Celery Scaling

### Add Celery Worker

**Using systemd template**:

```bash
# Enable multiple workers
systemctl --user enable --now celery-worker@1.service
systemctl --user enable --now celery-worker@2.service
systemctl --user enable --now celery-worker@3.service

# Verify
podman ps | grep celery-worker
```

### Queue-Specific Workers

**Dedicated workers per queue**:

```bash
# Trading queue (high priority)
systemctl --user start celery-worker-trading.service

# Accounts queue
systemctl --user start celery-worker-accounts.service

# General queue
systemctl --user start celery-worker-general.service
```

**Quadlet configuration**:

```ini
# celery-worker-trading.container
[Container]
Exec=celery -A senextrader worker \
    --queue=trading \
    --concurrency=8 \
    --loglevel=info \
    --max-tasks-per-child=50
```

## Auto-Scaling Strategy

### Metrics-Based Scaling

**Script** (`/opt/scripts/autoscale.sh`):

```bash
#!/bin/bash

# Configuration
MAX_DJANGO_INSTANCES=5
MIN_DJANGO_INSTANCES=2
CPU_THRESHOLD_UP=70
CPU_THRESHOLD_DOWN=30

# Get current instance count
CURRENT_INSTANCES=$(systemctl --user list-units 'django@*.service' --state=running | grep -c django@)

# Get average CPU usage
AVG_CPU=$(podman stats --no-stream --format "{{.CPUPerc}}" \
    $(podman ps --format "{{.Names}}" | grep django) | \
    sed 's/%//' | awk '{sum+=$1; count++} END {print sum/count}')

echo "Current instances: $CURRENT_INSTANCES, Avg CPU: $AVG_CPU%"

# Scale up
if (( $(echo "$AVG_CPU > $CPU_THRESHOLD_UP" | bc -l) )) && [ $CURRENT_INSTANCES -lt $MAX_DJANGO_INSTANCES ]; then
    NEXT_INSTANCE=$((CURRENT_INSTANCES + 1))
    echo "Scaling UP to $NEXT_INSTANCE instances"
    systemctl --user start django@${NEXT_INSTANCE}.service
    
    # Update Nginx
    sudo /opt/scripts/update-nginx-upstream.sh
    
# Scale down
elif (( $(echo "$AVG_CPU < $CPU_THRESHOLD_DOWN" | bc -l) )) && [ $CURRENT_INSTANCES -gt $MIN_DJANGO_INSTANCES ]; then
    echo "Scaling DOWN to $((CURRENT_INSTANCES - 1)) instances"
    systemctl --user stop django@${CURRENT_INSTANCES}.service
    
    # Update Nginx
    sudo /opt/scripts/update-nginx-upstream.sh
fi
```

**Schedule every 5 minutes**:

```bash
*/5 * * * * /opt/scripts/autoscale.sh >> /var/log/autoscale.log
```

## Multi-Server Deployment

### Server Roles

**Web Servers** (2+):
- Django/Daphne instances
- Nginx (or use separate load balancer)
- Celery workers (optional)

**Database Servers**:
- PostgreSQL primary
- PostgreSQL replica(s)
- PgBouncer

**Cache Servers**:
- Redis Sentinel cluster (3+ nodes)

**Task Queue Servers** (optional):
- Dedicated Celery workers

### Load Balancer Setup

**HAProxy on dedicated LB server**:

```haproxy
frontend django_frontend
    bind *:443 ssl crt /etc/letsencrypt/live/your-domain.com/combined.pem
    default_backend django_backend

backend django_backend
    balance roundrobin
    cookie SERVERID insert indirect nocache
    
    option httpchk GET /health/
    http-check expect status 200
    
    server web01 web01.internal:8000 check cookie web01
    server web02 web02.internal:8000 check cookie web02
    server web03 web03.internal:8000 check cookie web03
```

## Performance Optimization

### Database Query Optimization

**Enable query logging** (temporarily):

```sql
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- Log queries >1s
SELECT pg_reload_conf();
```

**Review slow queries**:

```sql
SELECT
    calls,
    mean_exec_time::numeric(10,2) as avg_time_ms,
    query
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;
```

**Add indexes**:

```sql
-- Find missing indexes
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE schemaname = 'public'
AND n_distinct > 100
AND abs(correlation) < 0.5;

-- Create composite index
CREATE INDEX idx_position_user_status ON trading_position(user_id, status);
CREATE INDEX idx_trade_created ON trading_trade(created_at DESC);
```

### Caching Strategy

**Cache expensive queries**:

```python
from django.core.cache import cache

def get_user_positions(user_id):
    cache_key = f'positions:user:{user_id}'
    positions = cache.get(cache_key)
    
    if positions is None:
        positions = Position.objects.filter(user_id=user_id).select_related('symbol')
        cache.set(cache_key, positions, timeout=120)  # 2 minutes
    
    return positions
```

**Invalidate on changes**:

```python
def update_position(position):
    position.save()
    cache_key = f'positions:user:{position.user_id}'
    cache.delete(cache_key)
```

## Cost Optimization

### Resource Right-Sizing

**Monitor actual usage**:

```bash
# Get average resource usage
podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# Adjust limits based on actual usage
```

**Idle worker consolidation**:

```bash
# If workers are idle <30% of the time, reduce count
# If queue length consistently >50, add workers
```

### Scheduled Scaling

**Scale down off-hours**:

```bash
# Crontab: Scale down at night (11 PM)
0 23 * * * systemctl --user stop django@3.service celery-worker@3.service

# Scale up before market opens (8 AM)
0 8 * * * systemctl --user start django@3.service celery-worker@3.service
```

## Monitoring Scaling Metrics

**Prometheus queries**:

```promql
# Django instance count
count(up{job="django"})

# Average CPU per Django instance
avg(rate(process_cpu_seconds_total{job="django"}[5m]))

# Request rate per instance
sum(rate(django_http_requests_total[5m])) by (instance)

# Queue length
celery_queue_length{queue="trading"}
```

**Grafana dashboard**:
- Instance count over time
- CPU/Memory per instance
- Request distribution
- Queue lengths
- Auto-scaling events

## Next Steps

1. **[Review implementation phases](./10-IMPLEMENTATION-PHASES.md)**
2. Test scaling procedures in staging
3. Document scaling runbooks
4. Set up auto-scaling alerts
