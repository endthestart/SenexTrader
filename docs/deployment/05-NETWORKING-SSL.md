# Networking and SSL/TLS Configuration

## Podman Network Setup

### Network Creation

**Quadlet Network File**: `~/.config/containers/systemd/senex_net.network`

```ini
[Unit]
Description=Senex Trader Application Network

[Network]
# Network configuration
NetworkName=senex_net
Driver=bridge
Subnet=172.20.0.0/16
Gateway=172.20.0.1
IPRange=172.20.1.0/24

# DNS
DNS=8.8.8.8
DNS=8.8.4.4

# Options
DisableDNS=false
Internal=false

[Install]
WantedBy=default.target
```

**Create via Ansible task**:
```yaml
- name: Create Podman network
  containers.podman.podman_network:
    name: senex_net
    driver: bridge
    subnet: 172.20.0.0/16
    gateway: 172.20.0.1
    state: present
  become: false
```

**Create manually**:
```bash
podman network create senex_net \
  --subnet 172.20.0.0/16 \
  --gateway 172.20.0.1
```

**Verify network**:
```bash
podman network ls
podman network inspect senex_net
```

### Service Discovery via DNS

Containers on the same Podman network can communicate using container names:

```python
# Django settings.py
DATABASES = {
    'default': {
        'HOST': 'postgres',  # Container name resolves via DNS
    }
}

CACHES = {
    'default': {
        'LOCATION': 'redis://redis:6379/0',  # Container name
    }
}
```

**Test DNS resolution**:
```bash
# From Django container
podman exec django ping postgres
podman exec django getent hosts redis
```

### Network Isolation

**Internal services** (PostgreSQL, Redis):
- Only accessible within Podman network
- Port publishing to 127.0.0.1 only (not 0.0.0.0)

**External services** (Django/Daphne):
- Accessible via Nginx reverse proxy
- Port 8000 published to localhost

**Example** (PostgreSQL):
```ini
PublishPort=127.0.0.1:5432:5432  # Not accessible from internet
```

## SSL/TLS with Let's Encrypt

### Prerequisites

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Ensure DNS is propagated
dig your-domain.com
nslookup your-domain.com
```

### Initial Certificate Request

**Method 1: Certbot with Nginx plugin** (recommended):

```bash
sudo certbot --nginx \
  -d your-domain.com \
  -d www.your-domain.com \
  --agree-tos \
  --email admin@your-domain.com \
  --non-interactive
```

**Method 2: Standalone** (if Nginx not installed yet):

```bash
# Stop Nginx if running
sudo systemctl stop nginx

# Request certificate
sudo certbot certonly --standalone \
  -d your-domain.com \
  -d www.your-domain.com \
  --agree-tos \
  --email admin@your-domain.com

# Start Nginx
sudo systemctl start nginx
```

**Method 3: HTTP-01 challenge with webroot**:

```bash
# Create webroot directory
sudo mkdir -p /var/www/certbot

# Request certificate
sudo certbot certonly --webroot \
  -w /var/www/certbot \
  -d your-domain.com \
  -d www.your-domain.com \
  --agree-tos \
  --email admin@your-domain.com
```

### Certificate Files Location

```
/etc/letsencrypt/
├── live/
│   └── your-domain.com/
│       ├── fullchain.pem      # Certificate + intermediate chain
│       ├── privkey.pem        # Private key
│       ├── cert.pem           # Certificate only
│       └── chain.pem          # Intermediate chain only
└── renewal/
    └── your-domain.com.conf   # Renewal configuration
```

### Automated Renewal

**Certbot Timer** (enabled by default):

```bash
# Check timer status
sudo systemctl status certbot.timer

# List timers
sudo systemctl list-timers certbot.timer

# Manual renewal test (dry run)
sudo certbot renew --dry-run

# Force renewal (if needed)
sudo certbot renew --force-renewal
```

**Custom renewal script** (if needed):

```bash
#!/bin/bash
# /usr/local/bin/renew-certs.sh

certbot renew --quiet --deploy-hook "systemctl reload nginx"

# Log renewal
echo "[$(date)] Certificate renewal check completed" >> /var/log/certbot-renewal.log
```

**Cron job** (alternative to timer):
```bash
# /etc/cron.d/certbot
0 2,14 * * * root /usr/local/bin/renew-certs.sh
```

### Nginx SSL Configuration

**Security best practices** (already in your-domain.com.conf):

```nginx
# Modern TLS configuration
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;

# Session cache
ssl_session_cache shared:SSL:50m;
ssl_session_timeout 1d;
ssl_session_tickets off;

# OCSP stapling
ssl_stapling on;
ssl_stapling_verify on;
ssl_trusted_certificate /etc/letsencrypt/live/your-domain.com/chain.pem;

# HSTS
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
```

**Test SSL configuration**:
```bash
# Nginx config test
sudo nginx -t

# SSL Labs test
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=your-domain.com

# Command-line test
openssl s_client -connect your-domain.com:443 -servername your-domain.com
```

### Wildcard Certificates (Optional)

**Requires DNS-01 challenge** (not HTTP-01):

```bash
# Install DNS plugin (example: Cloudflare)
sudo apt install python3-certbot-dns-cloudflare

# Create credentials file
cat > ~/.secrets/cloudflare.ini << EOF
dns_cloudflare_api_token = YOUR_API_TOKEN
EOF
chmod 600 ~/.secrets/cloudflare.ini

# Request wildcard certificate
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials ~/.secrets/cloudflare.ini \
  -d your-domain.com \
  -d '*.your-domain.com'
```

## WebSocket Configuration

### Nginx WebSocket Proxy

**Key configuration** (in your-domain.com.conf):

```nginx
location /ws/ {
    proxy_pass http://django_backend;
    
    # HTTP/1.1 required for WebSocket
    proxy_http_version 1.1;
    
    # WebSocket upgrade headers
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # Long timeout for persistent connections
    proxy_read_timeout 86400s;  # 24 hours
    proxy_send_timeout 86400s;
    proxy_connect_timeout 60s;
    
    # Disable buffering
    proxy_buffering off;
}
```

### Django Channels Configuration

**ASGI routing** (senex_trader/asgi.py):

```python
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from streaming.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
```

**Channel layer** (production.py):

```python
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get("REDIS_URL") + "/1"],  # Redis DB 1
            "capacity": 1500,
            "expiry": 60,
            "group_expiry": 300,
        },
    }
}
```

**WebSocket origin validation**:

```python
# In production.py or asgi.py
from channels.security.websocket import AllowedHostsOriginValidator

application = ProtocolTypeRouter({
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})

# Or custom validator
ALLOWED_WS_ORIGINS = os.environ.get("WS_ALLOWED_ORIGINS", "").split(",")
```

### Testing WebSocket Connections

**Browser console test**:
```javascript
// Open browser console on https://your-domain.com
const ws = new WebSocket('wss://your-domain.com/ws/streaming/');

ws.onopen = () => {
    console.log('WebSocket connected');
};

ws.onmessage = (event) => {
    console.log('Message:', JSON.parse(event.data));
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

ws.onclose = () => {
    console.log('WebSocket closed');
};
```

**Command-line test with wscat**:
```bash
# Install wscat
npm install -g wscat

# Test connection
wscat -c wss://your-domain.com/ws/streaming/

# With authentication (if needed)
wscat -c wss://your-domain.com/ws/streaming/ -H "Cookie: sessionid=YOUR_SESSION_ID"
```

**Python test**:
```python
import asyncio
import websockets

async def test_ws():
    uri = "wss://your-domain.com/ws/streaming/"
    async with websockets.connect(uri) as websocket:
        print("Connected!")
        # Wait for message
        message = await websocket.recv()
        print(f"Received: {message}")

asyncio.run(test_ws())
```

## Load Balancing (Phase 3 HA)

### HAProxy Configuration

**Install HAProxy**:
```bash
sudo apt install haproxy
```

**Configuration** (`/etc/haproxy/haproxy.cfg`):

```haproxy
global
    log /dev/log local0
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s
    user haproxy
    group haproxy
    daemon

    # SSL/TLS
    ssl-default-bind-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256
    ssl-default-bind-options ssl-min-ver TLSv1.2 no-tls-tickets

defaults
    log global
    mode http
    option httplog
    option dontlognull
    timeout connect 10s
    timeout client 86400s  # For WebSocket
    timeout server 86400s
    errorfile 400 /etc/haproxy/errors/400.http
    errorfile 403 /etc/haproxy/errors/403.http
    errorfile 408 /etc/haproxy/errors/408.http
    errorfile 500 /etc/haproxy/errors/500.http
    errorfile 502 /etc/haproxy/errors/502.http
    errorfile 503 /etc/haproxy/errors/503.http
    errorfile 504 /etc/haproxy/errors/504.http

frontend django_frontend
    bind *:80
    bind *:443 ssl crt /etc/letsencrypt/live/your-domain.com/combined.pem
    
    # HTTP to HTTPS redirect
    redirect scheme https code 301 if !{ ssl_fc }
    
    # HSTS header
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    
    default_backend django_backend

backend django_backend
    balance roundrobin
    
    # Sticky sessions using cookies
    cookie SERVERID insert indirect nocache
    
    # Health checks
    option httpchk GET /health/
    http-check expect status 200
    
    # Servers
    server django1 10.0.1.10:8000 check cookie django1 maxconn 100
    server django2 10.0.1.11:8000 check cookie django2 maxconn 100
    
    # Connection settings
    option http-server-close
    option forwardfor
```

**Combine SSL files for HAProxy**:
```bash
cat /etc/letsencrypt/live/your-domain.com/fullchain.pem \
    /etc/letsencrypt/live/your-domain.com/privkey.pem \
    > /etc/letsencrypt/live/your-domain.com/combined.pem
```

### Nginx Load Balancing (Alternative)

**Upstream configuration**:

```nginx
upstream django_backend {
    # Sticky sessions with ip_hash
    ip_hash;
    
    server 10.0.1.10:8000 max_fails=3 fail_timeout=30s weight=1;
    server 10.0.1.11:8000 max_fails=3 fail_timeout=30s weight=1;
    server 10.0.1.12:8000 max_fails=3 fail_timeout=30s weight=1 backup;
    
    # Connection pooling
    keepalive 32;
    keepalive_requests 100;
    keepalive_timeout 60s;
}

# Health check endpoint (Nginx Plus feature, or use external script)
location /health/ {
    access_log off;
    proxy_pass http://django_backend;
}
```

## Firewall Configuration

### UFW (Ubuntu/Debian)

```bash
# Install UFW
sudo apt install ufw

# Default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow SSH (CRITICAL: do this first!)
sudo ufw allow 22/tcp comment 'SSH'

# Allow HTTP/HTTPS
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'

# Optional: Allow from specific IPs only
# sudo ufw allow from 203.0.113.0/24 to any port 22 comment 'SSH from office'

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status verbose
```

### Firewalld (RHEL/Rocky/Fedora)

```bash
# Install firewalld
sudo dnf install firewalld

# Start and enable
sudo systemctl enable --now firewalld

# Allow services
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https

# Reload
sudo firewall-cmd --reload

# Check status
sudo firewall-cmd --list-all
```

### Docker/Podman Firewall Integration

**Issue**: Podman bypasses some firewall rules

**Solution**: Use firewalld zones or explicit iptables rules

```bash
# Add Podman network to trusted zone
sudo firewall-cmd --permanent --zone=trusted --add-source=172.20.0.0/16
sudo firewall-cmd --reload
```

## Network Security Best Practices

### Rate Limiting

Already configured in Nginx (see your-domain.com.conf):

```nginx
# Login endpoint: 5 requests per minute
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;

# API endpoints: 20 requests per second
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=20r/s;

# General: 10 requests per second
limit_req_zone $binary_remote_addr zone=general_limit:10m rate=10r/s;
```

### DDoS Protection

**Nginx configuration**:

```nginx
# Connection limits
limit_conn_zone $binary_remote_addr zone=addr:10m;
limit_conn addr 10;

# Request body size limit
client_max_body_size 10M;

# Timeouts
client_body_timeout 12;
client_header_timeout 12;
keepalive_timeout 15;
send_timeout 10;

# Buffer sizes
client_body_buffer_size 10K;
client_header_buffer_size 1k;
large_client_header_buffers 2 1k;
```

**Fail2ban integration**:

```bash
# Install fail2ban
sudo apt install fail2ban

# Create Nginx jail
sudo cat > /etc/fail2ban/jail.d/nginx.conf << EOF
[nginx-http-auth]
enabled = true

[nginx-limit-req]
enabled = true
filter = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 10
findtime = 600
bantime = 7200
EOF

sudo systemctl restart fail2ban
```

### CORS Configuration (if REST API exposed)

**Django settings**:

```python
# Install: pip install django-cors-headers

INSTALLED_APPS = [
    'corsheaders',
    # ...
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    # ... other middleware
]

CORS_ALLOWED_ORIGINS = [
    "https://your-domain.com",
    "https://www.your-domain.com",
]

# For development only:
# CORS_ALLOW_ALL_ORIGINS = True
```

## Troubleshooting

### Network Issues

**Container can't reach internet**:
```bash
# Check DNS resolution
podman exec django ping 8.8.8.8
podman exec django nslookup google.com

# Check network
podman network inspect senex_net

# Recreate network if needed
podman network rm senex_net
podman network create senex_net
```

**Containers can't communicate**:
```bash
# Verify both on same network
podman inspect postgres | grep NetworkMode
podman inspect django | grep NetworkMode

# Test connectivity
podman exec django ping postgres
podman exec django telnet redis 6379
```

### SSL Issues

**Certificate not found**:
```bash
# Check certificate files
ls -lah /etc/letsencrypt/live/your-domain.com/

# Verify certificate
openssl x509 -in /etc/letsencrypt/live/your-domain.com/cert.pem -text -noout
```

**Mixed content warnings**:
```bash
# Ensure all resources use HTTPS
# Check CSP headers in Nginx config
```

### WebSocket Issues

**Connection refused**:
```bash
# Check Nginx configuration
sudo nginx -t

# Verify upgrade headers
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  https://your-domain.com/ws/streaming/

# Check Django Channels
podman logs django | grep -i websocket
```

**Origin blocked**:
```python
# Check ALLOWED_HOSTS and WS_ALLOWED_ORIGINS
# In Django settings
print(settings.ALLOWED_HOSTS)
print(settings.WS_ALLOWED_ORIGINS)
```

## Next Steps

1. **[Apply security hardening](./06-SECURITY-HARDENING.md)**
2. **[Set up monitoring](./07-MONITORING-LOGGING.md)**
3. **[Configure backups](./08-BACKUP-DISASTER-RECOVERY.md)**
