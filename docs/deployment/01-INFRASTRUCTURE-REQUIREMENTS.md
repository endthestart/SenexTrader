# Infrastructure Requirements

## Server Specifications by Deployment Phase

### Phase 1: Single Server MVP

**Target**: 1,000 users, 500 trades/day

**Server Specification**:
- **CPU**: 4 cores (AMD EPYC or Intel Xeon)
- **RAM**: 8GB DDR4
- **Storage**: 80GB NVMe SSD
- **Network**: 1TB/month bandwidth, 1Gbps port
- **OS**: Ubuntu 24.04 LTS or Rocky Linux 9

**Recommended Providers**:
| Provider | Instance Type | Monthly Cost | Notes |
|----------|--------------|--------------|-------|
| Hetzner | CX41 | €12 (~$13) | Best value, EU/US locations |
| DigitalOcean | Basic 4GB | $48 | Global locations, simple UI |
| Vultr | High Frequency 4GB | $24 | NVMe storage, good performance |
| Linode | Dedicated 8GB | $60 | Predictable performance |

**Recommended**: Hetzner CX41 for cost efficiency, DigitalOcean for ease of use.

### Phase 2: Separated Services

**Target**: 5,000 users, 2,000 trades/day

**Django/Nginx Server**:
- **CPU**: 2 cores
- **RAM**: 4GB
- **Storage**: 40GB SSD
- **Cost**: ~$30/month

**PostgreSQL Server**:
- **CPU**: 2 cores
- **RAM**: 4GB (dedicated for database)
- **Storage**: 80GB SSD (20GB database + 60GB backups)
- **IOPS**: 3000+ (critical for trading data)
- **Cost**: ~$40/month

**Redis/Celery Server**:
- **CPU**: 2 cores
- **RAM**: 2GB
- **Storage**: 20GB SSD
- **Cost**: ~$20/month

**Total Monthly Cost**: $120-150/month

### Phase 3: High Availability

**Target**: 20,000 users, 10,000 trades/day, 99.9% uptime

**Load Balancer** (optional, can use Nginx on smallest VPS):
- **CPU**: 1 core
- **RAM**: 1GB
- **Cost**: $10/month or use floating IP with Nginx

**Django/Daphne (2x instances)**:
- **CPU**: 2 cores each
- **RAM**: 4GB each
- **Storage**: 40GB SSD each
- **Cost**: $60/month (2x $30)

**PostgreSQL Primary + Replica**:
- **CPU**: 2-4 cores each
- **RAM**: 4-8GB each
- **Storage**: 160GB SSD (80GB per instance)
- **Cost**: $100/month (2x $50)

**Redis Sentinel Cluster (3 instances)**:
- **CPU**: 1 core each
- **RAM**: 2GB each
- **Storage**: 20GB SSD each
- **Cost**: $60/month (3x $20)

**Celery Workers (2x instances)**:
- **CPU**: 2 cores each
- **RAM**: 2GB each
- **Cost**: $60/month (2x $30)

**Monitoring/Logging Server**:
- **CPU**: 2 cores
- **RAM**: 4GB
- **Storage**: 100GB SSD (log storage)
- **Cost**: $30/month

**Total Monthly Cost**: $300-350/month

## Network Requirements

### Firewall Rules

**Externally Accessible Ports**:
```bash
# SSH (restrict to known IPs in production)
22/tcp - SSH access

# HTTP/HTTPS (public web traffic)
80/tcp - HTTP (redirects to HTTPS)
443/tcp - HTTPS (Nginx)
```

**Internal Network Only** (Podman bridge network):
```bash
8000/tcp - Daphne ASGI server
5432/tcp - PostgreSQL
6379/tcp - Redis
5555/tcp - Celery Flower (monitoring, optional)
```

**Inter-Server Communication** (Phase 2+):
```bash
# PostgreSQL replication
5432/tcp - PostgreSQL (primary ↔ replica)

# Redis Sentinel
26379/tcp - Redis Sentinel

# Prometheus scraping
9090/tcp - Prometheus
3000/tcp - Grafana
```

### Domain Configuration

**Required DNS Records**:

```
# Primary domain (A record)
your-domain.com.               A       <PRIMARY_IP>

# WWW redirect (CNAME or A record)
www.your-domain.com.           CNAME   your-domain.com.

# Optional: API subdomain
api.your-domain.com.           A       <PRIMARY_IP>

# Optional: Monitoring (restrict with HTTP auth)
grafana.your-domain.com.       A       <MONITORING_IP>
```

**DNS TTL Recommendations**:
- **Production**: 300 seconds (5 minutes) - allows fast failover
- **After stable**: 3600 seconds (1 hour) - reduces DNS query load

**WebSocket Configuration**:
- Ensure DNS propagates before testing WebSocket connections
- WebSocket origin validation in Django requires correct domain names

### Network Bandwidth Estimates

**Per User (Monthly Average)**:
- **HTTP requests**: ~50MB/month (browsing, API calls)
- **WebSocket**: ~10MB/month (real-time quotes)
- **Static files**: ~5MB/month (cached)
- **Total**: ~65MB/user/month

**Scaling Calculation**:
- 1,000 users: ~65GB/month
- 5,000 users: ~325GB/month
- 20,000 users: ~1.3TB/month

**Recommended Bandwidth**: 1TB/month minimum, 2TB+ for Phase 3

### External Service Dependencies

**TastyTrade API**:
- **Endpoint**: `https://api.tastyworks.com`
- **Port**: 443 (HTTPS)
- **IP Whitelist**: Not required
- **Rate Limits**: Configured in Django settings
- **Outbound Traffic**: ~100MB/day (API calls, market data)

**DXFeed Streaming** (via TastyTrade):
- **Protocol**: WebSocket over HTTPS
- **Connection**: Long-lived (hours)
- **Bandwidth**: ~500KB-2MB/hour per stream

**Backup Storage** (S3-compatible):
- **Providers**: AWS S3, Backblaze B2, Wasabi, MinIO
- **Cost**: ~$0.005/GB/month
- **Traffic**:
  - PostgreSQL dumps: 500MB-5GB/day
  - Redis snapshots: 100MB-1GB/day
  - Media files: 1GB-10GB (one-time, incremental)

## Operating System Requirements

### Supported Distributions

**Recommended**:
- **Ubuntu 24.04 LTS** - Best Podman support, long-term support until 2029
- **Rocky Linux 9** - Enterprise stability, RHEL-compatible

**Also Supported**:
- Debian 12 (Bookworm)
- Fedora 40+
- AlmaLinux 9

**Not Recommended**:
- Ubuntu <22.04 (outdated Podman version)
- CentOS 7/8 (EOL or deprecated)
- Debian <11 (old packages)

### Required System Packages

```bash
# Core system
sudo apt update
sudo apt install -y \
    podman \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    ca-certificates \
    gnupg \
    lsb-release

# Security
sudo apt install -y \
    ufw \
    fail2ban \
    unattended-upgrades

# Monitoring
sudo apt install -y \
    htop \
    iotop \
    nethogs \
    sysstat

# Backup tools
sudo apt install -y \
    rsync \
    rclone \
    postgresql-client-16
```

### Podman Version Requirements

**Minimum**: Podman 4.4+ (for Quadlet support)
**Recommended**: Podman 5.0+ (latest features, security fixes)

**Check version**:
```bash
podman --version
# Output: podman version 5.0.0
```

**Upgrade if needed**:
```bash
# Ubuntu: Use Podman PPA for latest version
sudo add-apt-repository -y ppa:projectatomic/ppa
sudo apt update
sudo apt install -y podman
```

### Python Version

**Required**: Python 3.11+
**Recommended**: Python 3.12 (Django 5.2 support)

**Verify**:
```bash
python3 --version
# Output: Python 3.12.x
```

## Storage Configuration

### Disk Layout

**Phase 1: Single Server**
```
/dev/sda1   20GB    /                   (OS, system)
/dev/sda2   10GB    /var/lib/containers (Podman storage)
/dev/sda3   30GB    /var/lib/postgresql (PostgreSQL data)
/dev/sda4   10GB    /var/lib/redis      (Redis persistence)
/dev/sda5   10GB    /var/log            (Application logs)
```

**Phase 2+: Separated Servers**

PostgreSQL Server:
```
/dev/sda1   20GB    /                   (OS)
/dev/sda2   60GB    /var/lib/postgresql (Database + WAL)
/dev/sda3   60GB    /var/backups        (Local backups)
```

Redis/Celery Server:
```
/dev/sda1   20GB    /                   (OS)
/dev/sda2   10GB    /var/lib/redis      (Redis RDB + AOF)
```

### Podman Storage Configuration

**Storage Driver**: `overlay` (default, best performance)

**Rootless Storage Location**:
- **User containers**: `~/.local/share/containers/storage/`
- **User volumes**: `~/.local/share/containers/storage/volumes/`

**Volume Creation Example**:
```bash
# PostgreSQL data volume
podman volume create postgres_data

# Redis data volume
podman volume create redis_data

# Inspect volume location
podman volume inspect postgres_data
# Output shows Mountpoint: /home/senex/.local/share/containers/storage/volumes/postgres_data
```

### Backup Storage Requirements

**Retention Policy**:
- **PostgreSQL base backups**: 30 days
- **PostgreSQL WAL archives**: 30 days
- **Redis snapshots**: 7 days
- **Application logs**: 90 days
- **Media files**: Indefinite (incremental)

**Storage Calculation (Phase 2)**:

```
PostgreSQL:
  - Database size: 5GB (initial)
  - Daily base backup: 5GB compressed → 2GB
  - Daily growth: 100MB
  - 30-day retention: 2GB × 30 = 60GB
  - WAL archives: ~500MB/day × 30 = 15GB
  - Total PostgreSQL backups: 75GB

Redis:
  - RDB snapshot: 500MB compressed → 200MB
  - Hourly snapshots: 200MB × 24 = 4.8GB/day
  - 7-day retention: 34GB

Logs:
  - Application logs: 500MB/day
  - 90-day retention: 45GB

Media files: 5GB (slowly growing)

Total backup storage needed: ~160GB
```

**Recommended Backup Provider**:
| Provider | Cost/GB/month | Notes |
|----------|---------------|-------|
| Backblaze B2 | $0.006 | Cheapest, good for backups |
| Wasabi | $0.0059 | No egress fees |
| AWS S3 Glacier | $0.004 | Slowest retrieval |
| Hetzner Storage Box | €3.81/1TB | Best value for EU |

**Recommended**: Hetzner Storage Box for EU deployments, Backblaze B2 for US

## User and Permission Setup

### Service User Creation

**Create dedicated user** (rootless Podman):
```bash
# Create user
sudo useradd -m -s /bin/bash -G wheel senex

# Enable lingering (containers persist after logout)
sudo loginctl enable-linger senex

# Configure subuid/subgid for rootless containers
echo "senex:100000:65536" | sudo tee -a /etc/subuid
echo "senex:100000:65536" | sudo tee -a /etc/subgid
```

### Directory Permissions

```bash
# Application directory
sudo mkdir -p /opt/senex-trader
sudo chown senex:senex /opt/senex-trader

# Configuration directory
sudo mkdir -p /etc/senex-trader
sudo chown senex:senex /etc/senex-trader
sudo chmod 700 /etc/senex-trader  # Restrict access to secrets

# Log directory
sudo mkdir -p /var/log/senex-trader
sudo chown senex:senex /var/log/senex-trader

# Backup directory (if local)
sudo mkdir -p /var/backups/senex-trader
sudo chown senex:senex /var/backups/senex-trader
sudo chmod 700 /var/backups/senex-trader
```

## Pre-Deployment Checklist

### Server Access
- [ ] SSH key-based authentication configured
- [ ] Root login disabled
- [ ] Firewall (ufw/firewalld) configured
- [ ] Fail2ban installed and configured
- [ ] Service user (`senex`) created with lingering enabled

### Network Configuration
- [ ] Domain DNS records created (A, CNAME)
- [ ] DNS TTL set to 300 seconds
- [ ] Ports 80/443 open for HTTP/HTTPS
- [ ] Port 22 restricted to known IPs (optional but recommended)
- [ ] Outbound HTTPS (443) allowed for TastyTrade API

### Storage Setup
- [ ] Disk partitions created per layout
- [ ] `/var/lib/containers` directory exists (rootless: `~/.local/share/containers`)
- [ ] Sufficient disk space (80GB+ Phase 1, 160GB+ Phase 2)
- [ ] Backup storage account created (S3-compatible)

### Software Installation
- [ ] OS updated (`apt update && apt upgrade`)
- [ ] Podman 4.4+ installed
- [ ] Python 3.11+ installed
- [ ] Ansible installed on control machine
- [ ] PostgreSQL client tools installed (for backup restoration)

### Security
- [ ] Unattended upgrades enabled (automatic security updates)
- [ ] SELinux enabled (RHEL/Rocky) or AppArmor (Ubuntu)
- [ ] TLS certificates ready (Let's Encrypt will auto-generate)
- [ ] Ansible Vault password file created and secured

### Monitoring
- [ ] Prometheus/Grafana servers ready (Phase 2+)
- [ ] UptimeRobot or equivalent external monitoring configured
- [ ] Email/Slack alerts configured for critical events

## Cost Breakdown Summary

### Phase 1: MVP ($50-60/month)
- Server: $40-50
- Backup storage: $5-10
- Domain: $1/month (amortized)

### Phase 2: Production ($150-180/month)
- Django/Nginx server: $30
- PostgreSQL server: $40
- Redis/Celery server: $20
- Backup storage: $15
- Monitoring (self-hosted): $0
- Domain + CDN: $5

### Phase 3: High Availability ($350-400/month)
- Load balancer: $10
- Django/Daphne (2x): $60
- PostgreSQL (primary + replica): $100
- Redis Sentinel (3x): $60
- Celery workers (2x): $60
- Monitoring/Logging: $30
- Backup storage: $20
- CDN + domain: $10

## Next Steps

1. **[Provision servers](./10-IMPLEMENTATION-PHASES.md#week-1-infrastructure-setup)** based on target phase
2. **[Set up Ansible](./02-ANSIBLE-STRUCTURE.md)** control machine and inventory
3. **[Configure secrets](./03-SECRETS-MANAGEMENT.md)** with Ansible Vault
4. **[Deploy services](./04-SERVICE-CONFIGURATION.md)** with Quadlet and systemd

## References

- [Hetzner Cloud Pricing](https://www.hetzner.com/cloud)
- [DigitalOcean Pricing](https://www.digitalocean.com/pricing)
- [Podman Installation Guide](https://podman.io/getting-started/installation)
- [Ubuntu 24.04 LTS Release Notes](https://releases.ubuntu.com/24.04/)
