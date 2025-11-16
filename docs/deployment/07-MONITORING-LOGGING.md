# Monitoring and Logging

## Monitoring Strategy

**Monitoring Levels**:
1. **Infrastructure**: CPU, memory, disk, network
2. **Services**: Container health, service uptime
3. **Application**: Request rate, latency, errors
4. **Business**: Trading metrics, user activity

**Deployment Phases**:
- **Phase 1**: systemd health checks + external monitoring
- **Phase 2**: Prometheus + Grafana + structured logging
- **Phase 3**: Full observability stack with Loki

## Phase 1: Essential Monitoring

### systemd Health Checks

**Already configured in Quadlet files**:
```ini
HealthCmd=curl -f http://localhost:8000/health/ || exit 1
HealthInterval=30s
HealthOnFailure=kill
```

**Monitor service status**:
```bash
# Check all services
systemctl --user list-units '*django*' '*celery*' '*postgres*' '*redis*'

# Watch in real-time
watch -n 5 'systemctl --user is-active django celery-worker celery-beat'

# View failed services
systemctl --user --failed
```

### External Uptime Monitoring

**UptimeRobot** (Free tier):
1. Sign up at https://uptimerobot.com
2. Add HTTP(S) monitor:
   - URL: `https://your-domain.com/health/`
   - Interval: 5 minutes
   - Alert contacts: Email, Slack
3. Expected response: `{"status": "healthy"}`

**Healthchecks.io** (Alternative):
```bash
# Ping healthchecks.io from cron
*/5 * * * * curl -fsS --retry 3 https://hc-ping.com/YOUR-UUID-HERE > /dev/null
```

### Basic Log Monitoring

**View recent logs**:
```bash
# Django logs
journalctl --user -u django.service -n 100 --no-pager

# Celery logs
journalctl --user -u celery-worker.service -n 100 --no-pager

# PostgreSQL logs
podman logs postgres --tail 100

# Redis logs
podman logs redis --tail 100

# Nginx logs
sudo tail -f /var/log/nginx/error.log
```

**Alert on errors**:
```bash
#!/bin/bash
# /opt/scripts/error-alert.sh
ERROR_COUNT=$(journalctl --user -u django.service --since "5 minutes ago" | grep -c ERROR)
if [ $ERROR_COUNT -gt 10 ]; then
    echo "High error rate detected: $ERROR_COUNT errors in last 5 minutes" | \
        mail -s "ALERT: Django Errors" admin@your-domain.com
fi
```

## Phase 2: Prometheus + Grafana

### Prometheus Setup

**Installation via container**:

**Quadlet file**: `~/.config/containers/systemd/prometheus.container`

```ini
[Unit]
Description=Prometheus Monitoring
After=network-online.target

[Container]
Image=docker.io/prom/prometheus:latest
ContainerName=prometheus
AutoUpdate=registry

Network=senex_net.network
PublishPort=127.0.0.1:9090:9090

Volume=%h/senex-trader/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro,z
Volume=prometheus_data:/prometheus:Z

Exec=--config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time=30d \
  --web.console.libraries=/usr/share/prometheus/console_libraries \
  --web.console.templates=/usr/share/prometheus/consoles

Memory=512M

[Service]
Restart=always

[Install]
WantedBy=default.target
```

**Configuration** (`~/senex-trader/monitoring/prometheus.yml`):

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'senex-trader-production'
    environment: 'production'

# Alerting configuration
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

# Load rules
rule_files:
  - 'alerts.yml'

# Scrape configurations
scrape_configs:
  # Django application metrics
  - job_name: 'django'
    static_configs:
      - targets: ['django:8000']
    metrics_path: '/metrics'

  # PostgreSQL metrics (requires postgres_exporter)
  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']

  # Redis metrics (requires redis_exporter)
  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']

  # Node exporter (system metrics)
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']

  # Celery metrics (via flower or custom exporter)
  - job_name: 'celery'
    static_configs:
      - targets: ['flower:5555']
```

### Django Prometheus Integration

**Install django-prometheus**:
```bash
pip install django-prometheus
```

**Configure** (`settings/production.py`):
```python
INSTALLED_APPS = [
    'django_prometheus',
    # ... other apps
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',
    # ... other middleware
    'django_prometheus.middleware.PrometheusAfterMiddleware',
]

# Database wrapper
DATABASES = {
    'default': {
        'ENGINE': 'django_prometheus.db.backends.postgresql',
        # ... other settings
    }
}

# Cache wrapper
CACHES = {
    'default': {
        'BACKEND': 'django_prometheus.cache.backends.redis.RedisCache',
        # ... other settings
    }
}
```

**URL configuration** (`urls.py`):
```python
urlpatterns = [
    path('', include('django_prometheus.urls')),
    # ... other patterns
]
```

**Metrics exposed at**: `http://django:8000/metrics`

### Grafana Setup

**Quadlet file**: `~/.config/containers/systemd/grafana.container`

```ini
[Unit]
Description=Grafana Dashboard
After=prometheus.service

[Container]
Image=docker.io/grafana/grafana:latest
ContainerName=grafana
AutoUpdate=registry

Network=senex_net.network
PublishPort=127.0.0.1:3000:3000

Volume=grafana_data:/var/lib/grafana:Z

Environment=GF_SECURITY_ADMIN_PASSWORD=CHANGE_ME
Environment=GF_INSTALL_PLUGINS=redis-datasource,postgres-datasource

Memory=512M

[Service]
Restart=always

[Install]
WantedBy=default.target
```

**Access Grafana**:
```
http://localhost:3000
Default: admin / CHANGE_ME
```

**Add Prometheus data source**:
1. Configuration → Data Sources → Add data source
2. Select Prometheus
3. URL: `http://prometheus:9090`
4. Save & Test

### Grafana Dashboards

**Django Dashboard** (import ID: 17658 or create custom):

**Key Metrics**:
- Request rate (req/s)
- Response time (p50, p95, p99)
- Error rate (4xx, 5xx)
- Active database connections
- Cache hit rate

**Example Dashboard JSON** (`~/senex-trader/monitoring/django-dashboard.json`):
```json
{
  "dashboard": {
    "title": "Senex Trader - Django",
    "panels": [
      {
        "title": "Request Rate",
        "targets": [{
          "expr": "rate(django_http_requests_total[5m])"
        }]
      },
      {
        "title": "Response Time (p95)",
        "targets": [{
          "expr": "histogram_quantile(0.95, rate(django_http_requests_latency_seconds_bucket[5m]))"
        }]
      },
      {
        "title": "Error Rate",
        "targets": [{
          "expr": "rate(django_http_responses_total{status=~\"5..\"}[5m])"
        }]
      }
    ]
  }
}
```

**PostgreSQL Dashboard** (import ID: 9628):
- Connections
- Transaction rate
- Query performance
- Cache hit ratio
- Database size

**Redis Dashboard** (import ID: 11835):
- Memory usage
- Hit rate
- Commands per second
- Evictions
- Connected clients

### Alert Rules

**File**: `~/senex-trader/monitoring/alerts.yml`

```yaml
groups:
  - name: senextrader_alerts
    interval: 30s
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: rate(django_http_responses_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} req/s"

      # High response time
      - alert: HighResponseTime
        expr: histogram_quantile(0.95, rate(django_http_requests_latency_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High response time"
          description: "p95 latency is {{ $value }}s"

      # Database connections
      - alert: HighDatabaseConnections
        expr: pg_stat_database_numbackends > 180
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High database connection count"

      # Celery queue backlog
      - alert: CeleryQueueBacklog
        expr: celery_queue_length{queue="trading"} > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Celery queue backlog"

      # Low disk space
      - alert: LowDiskSpace
        expr: node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Low disk space (<10%)"

      # Service down
      - alert: ServiceDown
        expr: up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.job }} is down"
```

## Structured Logging

### Django Logging Configuration

**Production settings** (`settings/production.py`):

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d',
        },
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/senex-trader/django.log',
            'maxBytes': 100 * 1024 * 1024,  # 100MB
            'backupCount': 10,
            'formatter': 'json',
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/var/log/senex-trader/django-errors.log',
            'maxBytes': 100 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'json',
            'level': 'ERROR',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
        },
        'django.request': {
            'handlers': ['console', 'error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'trading': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'INFO',
        },
        'celery': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
        },
    },
}
```

**Install JSON formatter**:
```bash
pip install python-json-logger
```

### Nginx Access Logs (JSON format)

**Configuration** (`/etc/nginx/nginx.conf`):

```nginx
log_format json_combined escape=json
  '{'
    '"time_local":"$time_local",'
    '"remote_addr":"$remote_addr",'
    '"remote_user":"$remote_user",'
    '"request":"$request",'
    '"status": "$status",'
    '"body_bytes_sent":"$body_bytes_sent",'
    '"request_time":"$request_time",'
    '"http_referrer":"$http_referer",'
    '"http_user_agent":"$http_user_agent"'
  '}';

access_log /var/log/nginx/access.log json_combined;
```

### Log Rotation

**Systemd journal**:
```bash
# Configure journal retention
sudo mkdir -p /etc/systemd/journald.conf.d/
cat << EOF | sudo tee /etc/systemd/journald.conf.d/retention.conf
[Journal]
SystemMaxUse=1G
MaxRetentionSec=7day
EOF

sudo systemctl restart systemd-journald
```

**Logrotate** (for file logs):
```
# /etc/logrotate.d/senex-trader
/var/log/senex-trader/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 senex senex
    sharedscripts
    postrotate
        systemctl --user kill -s HUP django.service
    endscript
}
```

## Phase 3: Log Aggregation with Loki

### Loki Setup

**Quadlet file**: `~/.config/containers/systemd/loki.container`

```ini
[Unit]
Description=Grafana Loki
After=network-online.target

[Container]
Image=docker.io/grafana/loki:latest
ContainerName=loki
AutoUpdate=registry

Network=senex_net.network
PublishPort=127.0.0.1:3100:3100

Volume=%h/senex-trader/monitoring/loki-config.yml:/etc/loki/local-config.yaml:ro,z
Volume=loki_data:/loki:Z

Memory=1G

[Service]
Restart=always

[Install]
WantedBy=default.target
```

**Configuration** (`~/senex-trader/monitoring/loki-config.yml`):

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

ingester:
  lifecycler:
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
  chunk_idle_period: 5m
  chunk_retain_period: 30s

schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

storage_config:
  boltdb_shipper:
    active_index_directory: /loki/index
    cache_location: /loki/index_cache
    shared_store: filesystem
  filesystem:
    directory: /loki/chunks

limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  retention_period: 720h  # 30 days

chunk_store_config:
  max_look_back_period: 720h

table_manager:
  retention_deletes_enabled: true
  retention_period: 720h
```

### Promtail (Log Shipper)

**Quadlet file**: `~/.config/containers/systemd/promtail.container`

```ini
[Unit]
Description=Promtail Log Shipper
After=loki.service

[Container]
Image=docker.io/grafana/promtail:latest
ContainerName=promtail

Network=senex_net.network

Volume=%h/senex-trader/monitoring/promtail-config.yml:/etc/promtail/config.yml:ro,z
Volume=/var/log:/var/log:ro,z

[Service]
Restart=always

[Install]
WantedBy=default.target
```

**Configuration** (`~/senex-trader/monitoring/promtail-config.yml`):

```yaml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  # Django logs via journald
  - job_name: django
    journal:
      matches: _SYSTEMD_UNIT=django.service
    relabel_configs:
      - source_labels: ['__journal__systemd_unit']
        target_label: 'unit'

  # Celery logs
  - job_name: celery
    journal:
      matches: _SYSTEMD_UNIT=celery-worker.service
    relabel_configs:
      - source_labels: ['__journal__systemd_unit']
        target_label: 'unit'

  # Nginx logs
  - job_name: nginx
    static_configs:
      - targets:
          - localhost
        labels:
          job: nginx
          __path__: /var/log/nginx/access.log
```

### Query Logs in Grafana

**Add Loki data source**:
1. Configuration → Data Sources → Add Loki
2. URL: `http://loki:3100`
3. Save & Test

**LogQL queries**:
```
# All Django errors
{unit="django.service"} |= "ERROR"

# Slow requests (>1s)
{job="nginx"} | json | request_time > 1

# Celery task failures
{unit="celery-worker.service"} |= "Task failed"

# Search for specific user
{unit="django.service"} |= "user_id=123"
```

## Key Metrics to Monitor

### Application Metrics

| Metric | Threshold | Action |
|--------|-----------|--------|
| Request rate | - | Baseline normal |
| p95 latency | >2s | Investigate slow queries |
| Error rate (5xx) | >1% | Immediate investigation |
| WebSocket connections | >1500/instance | Scale Daphne |

### Database Metrics

| Metric | Threshold | Action |
|--------|-----------|--------|
| Connection usage | >90% | Add PgBouncer or scale |
| Query time | p95 >500ms | Optimize queries |
| Cache hit ratio | <90% | Increase shared_buffers |
| Database size | >80% disk | Archive old data |

### Cache Metrics

| Metric | Threshold | Action |
|--------|-----------|--------|
| Memory usage | >90% | Increase maxmemory or evict |
| Hit rate | <80% | Review cache strategy |
| Evictions | >1000/s | Increase memory |

### Celery Metrics

| Metric | Threshold | Action |
|--------|-----------|--------|
| Queue length | >100 | Add workers |
| Task success rate | <95% | Investigate failures |
| Task duration | p95 >60s | Optimize tasks |

## Alerting

### Email Alerts

**Install postfix**:
```bash
sudo apt install postfix mailutils
sudo dpkg-reconfigure postfix  # Select "Internet Site"
```

**Test email**:
```bash
echo "Test alert" | mail -s "Test" admin@your-domain.com
```

### Slack Alerts

**Alertmanager configuration** (`alertmanager.yml`):
```yaml
route:
  receiver: 'slack-notifications'
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#alerts'
        title: 'Senex Trader Alert'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
```

## Next Steps

1. **[Configure backup and DR](./08-BACKUP-DISASTER-RECOVERY.md)**
2. **[Plan scaling strategy](./09-SCALING-STRATEGY.md)**
3. **[Review implementation phases](./10-IMPLEMENTATION-PHASES.md)**
