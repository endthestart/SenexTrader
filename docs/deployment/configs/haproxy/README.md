# HAProxy Load Balancer Configuration for Senex Trader

HAProxy configuration for Phase 3 High Availability deployment.

## Features

- **Load Balancing**: Distributes traffic across multiple Django/Daphne instances
- **SSL Termination**: Handles HTTPS encryption/decryption
- **WebSocket Support**: Sticky sessions for WebSocket connections
- **Health Checks**: Automatic failover for unhealthy backends
- **Rate Limiting**: DDoS protection using stick tables
- **PostgreSQL Load Balancing**: Optional read replica routing
- **Redis Load Balancing**: Sentinel-aware routing
- **Statistics Dashboard**: Real-time monitoring at :8404/stats

## Installation

### 1. Install HAProxy

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install haproxy

# Verify version (requires 2.4+)
haproxy -v
```

### 2. Deploy Configuration

```bash
# Backup existing config
sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.backup

# Copy new configuration
sudo cp haproxy.cfg /etc/haproxy/haproxy.cfg

# Test configuration
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
```

### 3. Configure SSL Certificate

HAProxy needs a combined certificate file:

```bash
# Combine Let's Encrypt certificate files
sudo cat /etc/letsencrypt/live/your-domain.com/fullchain.pem \
        /etc/letsencrypt/live/your-domain.com/privkey.pem \
        > /etc/letsencrypt/live/your-domain.com/combined.pem

# Set permissions
sudo chmod 600 /etc/letsencrypt/live/your-domain.com/combined.pem
```

**Auto-renewal hook** (`/etc/letsencrypt/renewal-hooks/deploy/haproxy-reload.sh`):

```bash
#!/bin/bash
cat /etc/letsencrypt/live/your-domain.com/fullchain.pem \
    /etc/letsencrypt/live/your-domain.com/privkey.pem \
    > /etc/letsencrypt/live/your-domain.com/combined.pem
chmod 600 /etc/letsencrypt/live/your-domain.com/combined.pem
systemctl reload haproxy
```

```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/haproxy-reload.sh
```

### 4. Update Backend Server IPs

Edit `haproxy.cfg` and replace placeholders:

```cfg
# Replace web01.internal, web02.internal, web03.internal
server web01 10.0.1.10:8000 check cookie web01 maxconn 500
server web02 10.0.1.11:8000 check cookie web02 maxconn 500
server web03 10.0.1.12:8000 check cookie web03 maxconn 500
```

### 5. Start HAProxy

```bash
# Enable and start
sudo systemctl enable haproxy
sudo systemctl start haproxy

# Check status
sudo systemctl status haproxy

# View logs
sudo journalctl -u haproxy -f
```

## Testing

### Health Checks

```bash
# Test HTTP -> HTTPS redirect
curl -I http://your-domain.com
# Should return: 301 Moved Permanently

# Test HTTPS
curl -I https://your-domain.com
# Should return: 200 OK

# Test WebSocket upgrade
curl -I -H "Upgrade: websocket" -H "Connection: Upgrade" https://your-domain.com/ws/
```

### Load Distribution

```bash
# Make multiple requests and check distribution
for i in {1..10}; do
  curl -s https://your-domain.com/health/ | jq .server
done

# Should see different server names (web01, web02, web03)
```

### Stats Dashboard

Open browser to:
```
http://your-haproxy-ip:8404/stats
```

Login:
- Username: `admin`
- Password: `CHANGE_THIS_PASSWORD` (update in config!)

## Monitoring

### HAProxy Stats Socket

```bash
# Install socat
sudo apt install socat

# Show info
echo "show info" | sudo socat stdio /run/haproxy/admin.sock

# Show stats
echo "show stat" | sudo socat stdio /run/haproxy/admin.sock

# Show servers
echo "show servers state" | sudo socat stdio /run/haproxy/admin.sock

# Disable server (maintenance)
echo "disable server django_backend/web02" | sudo socat stdio /run/haproxy/admin.sock

# Enable server
echo "enable server django_backend/web02" | sudo socat stdio /run/haproxy/admin.sock
```

### Prometheus Metrics

HAProxy exposes metrics at:
```
http://your-haproxy-ip:9101/metrics
```

Add to Prometheus scrape config:

```yaml
- job_name: 'haproxy'
  static_configs:
    - targets: ['haproxy-server:9101']
```

### Key Metrics

- **Frontend connections**: How many clients are connected
- **Backend active servers**: Number of healthy backends
- **Queue depth**: Requests waiting for available backend
- **Response time**: Average response time
- **Error rate**: 4xx/5xx errors per second

## Advanced Features

### Rate Limiting

Configure rate limits in `haproxy.cfg`:

```cfg
# Limit to 100 requests per 10 seconds per IP
http-request track-sc0 src
acl abuse sc0_http_req_rate gt 100
http-request deny if abuse
```

### Sticky Sessions

Cookie-based sticky sessions ensure WebSocket connections stay on same server:

```cfg
cookie SERVERID insert indirect nocache
server web01 10.0.1.10:8000 check cookie web01
```

### SSL/TLS Optimization

Modern cipher suites are configured for security and performance:

- TLS 1.2+ only
- ECDHE key exchange
- AES-GCM and ChaCha20 ciphers
- HTTP/2 support (ALPN)

### Health Check Configuration

Customize health checks per backend:

```cfg
option httpchk GET /health/
http-check expect status 200
http-check send-state
```

### Maintenance Mode

To enable maintenance mode:

1. Uncomment maintenance backend in config
2. Set all servers to maintenance:

```bash
for server in web01 web02 web03; do
  echo "set server django_backend/$server state maint" | sudo socat stdio /run/haproxy/admin.sock
done
```

3. Or redirect frontend to maintenance backend:

```cfg
use_backend maintenance_backend
```

## Load Balancing Algorithms

### Round Robin (default)

Distributes requests evenly across all servers:

```cfg
balance roundrobin
```

### Least Connections

Routes to server with fewest active connections:

```cfg
balance leastconn
```

### Source IP Hash

Same client always goes to same server (WebSocket):

```cfg
balance source
```

### URI Hash

Route based on URL (for caching):

```cfg
balance uri
```

## Database Load Balancing

HAProxy can route database connections:

- **Writes**: Always go to primary
- **Reads**: Distributed across replicas

Configure application to use HAProxy port (5433) instead of direct PostgreSQL (5432).

## Troubleshooting

### Backend Servers Showing as Down

```bash
# Check health check endpoint
curl http://web01.internal:8000/health/

# View HAProxy logs
sudo journalctl -u haproxy -n 100

# Check firewall
sudo ufw status
```

### SSL Certificate Errors

```bash
# Verify certificate file
sudo openssl x509 -in /etc/letsencrypt/live/your-domain.com/combined.pem -text -noout

# Check HAProxy SSL binding
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
```

### High Queue Depth

If requests are queuing:

1. Add more backend servers
2. Increase `maxconn` per server
3. Optimize application response time

### Connection Timeouts

Adjust timeouts for slow endpoints:

```cfg
timeout server 120s
timeout client 120s
```

## Performance Tuning

### System Limits

```bash
# Increase file descriptors
sudo tee -a /etc/security/limits.conf << EOF
haproxy soft nofile 65536
haproxy hard nofile 65536
EOF

# Kernel tuning
sudo tee -a /etc/sysctl.conf << EOF
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65000
net.core.somaxconn = 4096
EOF

sudo sysctl -p
```

### HAProxy Tuning

```cfg
global
    maxconn 8192
    nbproc 2  # Or nbthread for 2.4+
    cpu-map auto:1/1-2 0-1

defaults
    maxconn 4096
```

## Security

- Run as unprivileged `haproxy` user
- Chroot to `/var/lib/haproxy`
- Rate limiting enabled
- Security headers configured
- TLS 1.2+ only
- Strong cipher suites

## Backup Configuration

Always keep a tested backup configuration:

```bash
# Before changes
sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.$(date +%Y%m%d)

# Rollback if needed
sudo cp /etc/haproxy/haproxy.cfg.20250108 /etc/haproxy/haproxy.cfg
sudo systemctl reload haproxy
```

## References

- [HAProxy Documentation](https://www.haproxy.org/doc.html)
- [HAProxy Configuration Manual](https://cbonte.github.io/haproxy-dconv/)
- [HAProxy Best Practices](https://www.haproxy.com/blog/)
