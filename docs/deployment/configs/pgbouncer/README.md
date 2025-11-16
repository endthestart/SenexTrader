# PgBouncer Configuration for Senex Trader

PgBouncer is a lightweight connection pooler for PostgreSQL, essential for scaling Django applications.

## Why PgBouncer?

- **Reduces database connections**: Django + Celery can create 200+ connections. PgBouncer pools them to 25-50 actual PostgreSQL connections.
- **Improves performance**: Connection reuse is faster than creating new connections.
- **Prevents connection exhaustion**: PostgreSQL has limits (typically 100-200 connections).

## Installation

```bash
sudo apt update
sudo apt install pgbouncer
```

## Configuration

### 1. Copy Configuration Files

```bash
# Main configuration
sudo cp pgbouncer.ini /etc/pgbouncer/pgbouncer.ini

# Create userlist
sudo touch /etc/pgbouncer/userlist.txt
sudo chmod 600 /etc/pgbouncer/userlist.txt
```

### 2. Generate User Password Hashes

```bash
# Generate MD5 hash for database user
DB_USER="senex_user"
DB_PASSWORD="your_database_password"

# Create hash
HASH=$(echo -n "${DB_PASSWORD}${DB_USER}" | md5sum | awk '{print $1}')

# Add to userlist.txt
echo "\"${DB_USER}\" \"md5${HASH}\"" | sudo tee -a /etc/pgbouncer/userlist.txt
```

### 3. Configure Django to Use PgBouncer

**settings/production.py**:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'senextrader',
        'USER': 'senex_user',
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': 'localhost',
        'PORT': '6432',  # PgBouncer port (not 5432!)

        # CRITICAL: Required for transaction pooling
        'CONN_MAX_AGE': None,  # Let PgBouncer manage connections
        'DISABLE_SERVER_SIDE_CURSORS': True,  # Required for transaction mode

        'OPTIONS': {
            'connect_timeout': 10,
        }
    }
}
```

### 4. Start PgBouncer

```bash
# Enable and start
sudo systemctl enable pgbouncer
sudo systemctl start pgbouncer

# Check status
sudo systemctl status pgbouncer

# View logs
sudo journalctl -u pgbouncer -f
```

## Verification

### Test Connection

```bash
# Connect through PgBouncer
psql -h localhost -p 6432 -U senex_user -d senextrader

# Should connect successfully
```

### Monitor PgBouncer

```bash
# Connect to PgBouncer admin console
psql -h localhost -p 6432 -U postgres pgbouncer

# View pools
SHOW POOLS;

# View clients
SHOW CLIENTS;

# View servers (actual PostgreSQL connections)
SHOW SERVERS;

# View statistics
SHOW STATS;

# View configuration
SHOW CONFIG;
```

### Expected Output (SHOW POOLS)

```
 database     | user       | cl_active | cl_waiting | sv_active | sv_idle | sv_used | sv_tested | sv_login | maxwait | pool_mode
--------------+------------+-----------+------------+-----------+---------+---------+-----------+----------+---------+-----------
 senextrader | senex_user |         5 |          0 |         3 |       2 |       0 |         0 |        0 |       0 | transaction
```

**Key metrics**:
- `cl_active`: Active client connections (e.g., 150)
- `sv_active`: Active server connections (e.g., 20)
- `sv_idle`: Idle server connections available for reuse (e.g., 5)
- Ratio shows pooling efficiency: 150 clients using only 25 server connections

## Django Settings Explained

### CONN_MAX_AGE = None

In transaction pooling mode, PgBouncer manages connection lifetime. Setting `CONN_MAX_AGE=None` prevents Django from closing connections.

### DISABLE_SERVER_SIDE_CURSORS = True

Server-side cursors require session pooling (holds state). Transaction pooling doesn't maintain state, so we disable cursors.

**Impact**: Queries using `.iterator()` will fetch all results into memory. For large querysets, use pagination instead:

```python
# Bad with transaction pooling
for obj in Model.objects.all().iterator():
    process(obj)

# Good
from django.core.paginator import Paginator
paginator = Paginator(Model.objects.all(), 1000)
for page_num in paginator.page_range:
    for obj in paginator.page(page_num):
        process(obj)
```

## Tuning

### For Django + Celery

Typical setup with 2 Django instances + 2 Celery workers:

```ini
[pgbouncer]
max_client_conn = 200        # Total Django + Celery connections
default_pool_size = 25       # Actual PostgreSQL connections
reserve_pool_size = 5        # Emergency connections
pool_mode = transaction      # CRITICAL for Django
```

**Calculation**:
- Django: 2 instances × 50 connections = 100
- Celery: 2 workers × 50 connections = 100
- Total clients: 200
- Actual server connections: 25-30

### Adjusting Pool Size

If you see connection errors, increase `default_pool_size`:

```bash
# Edit config
sudo nano /etc/pgbouncer/pgbouncer.ini

# Reload (no downtime)
sudo systemctl reload pgbouncer
```

## Troubleshooting

### "No more connections allowed"

Increase `max_client_conn`:

```ini
max_client_conn = 300
```

### "Server connection quota exceeded"

Increase `default_pool_size`:

```ini
default_pool_size = 50
```

### Check PostgreSQL Connection Limit

```sql
SELECT max_connections FROM pg_settings;
-- Typical: 100

-- View current connections
SELECT count(*) FROM pg_stat_activity;
```

Ensure `default_pool_size < max_connections`.

### Authentication Failures

Verify userlist.txt hash:

```bash
# Regenerate hash
echo -n "passwordusername" | md5sum

# Check file permissions
ls -l /etc/pgbouncer/userlist.txt
# Should be: -rw------- 1 postgres postgres
```

## Monitoring

### Prometheus Exporter

Install PgBouncer exporter for metrics:

```bash
wget https://github.com/prometheus-community/pgbouncer_exporter/releases/latest/download/pgbouncer_exporter
chmod +x pgbouncer_exporter

./pgbouncer_exporter \
  --pgbouncer.connection-string="postgres://postgres@localhost:6432/pgbouncer?sslmode=disable"
```

### Key Metrics to Watch

- `pgbouncer_pools_server_active_connections`: Should be < `default_pool_size`
- `pgbouncer_pools_client_waiting_connections`: Should be 0 (if > 0, increase pool size)
- `pgbouncer_stats_queries_total`: Query throughput

## Systemd Service

PgBouncer systemd service is installed automatically. To customize:

```bash
sudo systemctl edit pgbouncer
```

## Security

- Run as `postgres` user (already configured)
- Bind to localhost only (already configured)
- Use MD5 hashes for passwords (already configured)
- Restrict admin access to `postgres` user only

## References

- [Official Documentation](http://www.pgbouncer.org/)
- [Django with PgBouncer](https://docs.djangoproject.com/en/5.0/ref/databases/#transaction-pooling-server-side-cursors)
