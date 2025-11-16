# Prometheus Configuration for Senex Trader

Complete Prometheus monitoring setup for Django application and infrastructure.

## Quick Start

### 1. Deploy Prometheus Container

```bash
# Create configuration directory
mkdir -p ~/senex-trader/prometheus/{data,alerts}

# Copy configuration files
cp prometheus.yml ~/senex-trader/prometheus/
cp -r alerts/ ~/senex-trader/prometheus/

# Create Prometheus Quadlet file
cat > ~/.config/containers/systemd/prometheus.container << 'EOF'
[Unit]
Description=Prometheus Monitoring
After=network-online.target

[Container]
Image=docker.io/prom/prometheus:latest
ContainerName=prometheus
Network=senex_net
PublishPort=9090:9090

Volume=%h/senex-trader/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro,Z
Volume=%h/senex-trader/prometheus/alerts:/etc/prometheus/alerts:ro,Z
Volume=%h/senex-trader/prometheus/data:/prometheus:Z

Exec=--config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/prometheus \
    --storage.tsdb.retention.time=30d \
    --web.console.libraries=/usr/share/prometheus/console_libraries \
    --web.console.templates=/usr/share/prometheus/consoles \
    --web.enable-lifecycle

HealthCmd=wget --no-verbose --tries=1 --spider http://localhost:9090/-/healthy || exit 1
HealthInterval=30s

Memory=1G

[Service]
Restart=always

[Install]
WantedBy=default.target
EOF

# Start Prometheus
systemctl --user daemon-reload
systemctl --user enable --now prometheus.service
```

### 2. Install Exporters

#### Node Exporter (System Metrics)

```bash
# Download and install
wget https://github.com/prometheus/node_exporter/releases/latest/download/node_exporter-*.linux-amd64.tar.gz
tar xvfz node_exporter-*.linux-amd64.tar.gz
sudo mv node_exporter-*/node_exporter /usr/local/bin/

# Create systemd service
sudo tee /etc/systemd/system/node_exporter.service << 'EOF'
[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/node_exporter
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now node_exporter
```

#### PostgreSQL Exporter

```bash
# Install
wget https://github.com/prometheus-community/postgres_exporter/releases/latest/download/postgres_exporter-*.linux-amd64.tar.gz
tar xvfz postgres_exporter-*.linux-amd64.tar.gz
sudo mv postgres_exporter-*/postgres_exporter /usr/local/bin/

# Create connection string
export DATA_SOURCE_NAME="postgresql://senex_user:PASSWORD@localhost:5432/senex_trader?sslmode=disable"

# Create systemd service
sudo tee /etc/systemd/system/postgres_exporter.service << 'EOF'
[Unit]
Description=PostgreSQL Exporter
After=postgresql.service

[Service]
Type=simple
Environment="DATA_SOURCE_NAME=postgresql://senex_user:PASSWORD@localhost:5432/senex_trader?sslmode=disable"
ExecStart=/usr/local/bin/postgres_exporter
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now postgres_exporter
```

#### Redis Exporter

```bash
# Install
wget https://github.com/oliver006/redis_exporter/releases/latest/download/redis_exporter-*.linux-amd64.tar.gz
tar xvfz redis_exporter-*.linux-amd64.tar.gz
sudo mv redis_exporter-*/redis_exporter /usr/local/bin/

# Create systemd service
sudo tee /etc/systemd/system/redis_exporter.service << 'EOF'
[Unit]
Description=Redis Exporter
After=redis.service

[Service]
Type=simple
Environment="REDIS_ADDR=localhost:6379"
Environment="REDIS_PASSWORD=YOUR_REDIS_PASSWORD"
ExecStart=/usr/local/bin/redis_exporter
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now redis_exporter
```

### 3. Configure Django for Metrics

**Install django-prometheus**:

```bash
pip install django-prometheus
```

**settings/production.py**:

```python
INSTALLED_APPS = [
    'django_prometheus',  # Must be first
    # ... other apps
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',  # First
    # ... other middleware
    'django_prometheus.middleware.PrometheusAfterMiddleware',   # Last
]

# Metrics configuration
PROMETHEUS_EXPORT_MIGRATIONS = False
```

**urls.py**:

```python
urlpatterns = [
    path('', include('django_prometheus.urls')),  # /metrics endpoint
    # ... other URLs
]
```

### 4. Access Prometheus

```bash
# Open in browser
http://your-server-ip:9090

# Or tunnel if needed
ssh -L 9090:localhost:9090 senex@your-domain.com
# Then visit: http://localhost:9090
```

## Alert Rules

Alert rules are organized by component:

- **django.yml**: Django application alerts
- **infrastructure.yml**: PostgreSQL, Redis, system alerts
- **celery.yml**: Celery worker and queue alerts

### Testing Alerts

```bash
# Check alert rules syntax
podman exec prometheus promtool check rules /etc/prometheus/alerts/*.yml

# View active alerts
curl http://localhost:9090/api/v1/alerts
```

## Key Metrics

### Django

```promql
# Request rate
rate(django_http_requests_total[5m])

# Error rate
rate(django_http_responses_total{status=~"5.."}[5m])

# Response time (95th percentile)
histogram_quantile(0.95, rate(django_http_request_duration_seconds_bucket[5m]))

# Database query count
rate(django_db_query_total[5m])

# Cache hit rate
rate(django_cache_hits_total[5m]) / (rate(django_cache_hits_total[5m]) + rate(django_cache_misses_total[5m]))
```

### PostgreSQL

```promql
# Connection usage
pg_stat_database_numbackends / pg_settings_max_connections

# Transaction rate
rate(pg_stat_database_xact_commit[5m])

# Locks
pg_locks_count

# Slow queries
pg_stat_statements_mean_exec_time_seconds
```

### Redis

```promql
# Memory usage
redis_memory_used_bytes / redis_memory_max_bytes

# Hit rate
rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m]))

# Connected clients
redis_connected_clients

# Commands per second
rate(redis_commands_processed_total[5m])
```

### System

```promql
# CPU usage
100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Memory usage
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100

# Disk usage
(1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100

# Network traffic
rate(node_network_receive_bytes_total[5m])
rate(node_network_transmit_bytes_total[5m])
```

## Grafana Integration

See [07-MONITORING-LOGGING.md](../../07-MONITORING-LOGGING.md) for Grafana setup and dashboard configuration.

## Retention

Default retention is 30 days. Adjust in Quadlet file:

```ini
Exec=--storage.tsdb.retention.time=90d
```

## Troubleshooting

### Prometheus Not Scraping Targets

```bash
# Check target status
curl http://localhost:9090/api/v1/targets

# View Prometheus logs
podman logs prometheus

# Test exporter manually
curl http://localhost:9100/metrics  # Node exporter
curl http://localhost:8000/metrics  # Django
```

### High Memory Usage

Reduce retention or increase memory limit:

```ini
Memory=2G
Exec=--storage.tsdb.retention.time=15d
```

### Slow Queries

Prometheus query performance tips:

- Use recording rules for expensive queries
- Limit cardinality (fewer unique label combinations)
- Use appropriate scrape intervals

## Security

- Prometheus exposed only on localhost by default
- Use Nginx reverse proxy with authentication for external access
- No authentication required for internal metrics endpoints
- Consider using TLS for exporter communications in production

## References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [django-prometheus](https://github.com/korfuri/django-prometheus)
- [Exporters](https://prometheus.io/docs/instrumenting/exporters/)
