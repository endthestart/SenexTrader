# Implementation Phases

## Overview

Week-by-week implementation plan for deploying Senex Trader to production.

**Phases**:
- **Phase 1** (Week 1-2): MVP Single Server
- **Phase 2** (Week 3-4): Production Ready with Monitoring
- **Phase 3** (Week 5-8): High Availability

## Phase 1: MVP Single Server (Week 1-2)

**Goal**: Deploy functional single-server instance
**Cost**: ~$50/month
**Capacity**: 1,000 users, 500 trades/day

### Week 1: Infrastructure Setup

#### Day 1: Server Provisioning

**Tasks**:
1. Provision VPS (Hetzner CX41 or equivalent)
2. Configure DNS A record
3. Set up SSH access
4. Create service user

**Commands**:
```bash
# On server (as root)
useradd -m -s /bin/bash -G sudo senex
mkdir -p /home/senex/.ssh
cat > /home/senex/.ssh/authorized_keys << EOF
your-ssh-public-key-here
EOF
chmod 700 /home/senex/.ssh
chmod 600 /home/senex/.ssh/authorized_keys
chown -R senex:senex /home/senex/.ssh

# Disable root login
sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd

# Test SSH
ssh senex@SERVER_IP
```

**Verification**:
- [ ] Can SSH as senex user
- [ ] DNS resolves: `dig your-domain.com`
- [ ] Server accessible via domain

#### Day 2: System Preparation

**Tasks**:
1. Install system packages
2. Configure firewall
3. Set up Podman
4. Enable systemd lingering

**Script** (`setup-system.sh`):
```bash
#!/bin/bash
# Run as root

# Update system
apt update && apt upgrade -y

# Install packages
apt install -y \
    podman \
    python3 \
    python3-pip \
    git \
    curl \
    ufw \
    fail2ban \
    unattended-upgrades \
    nginx \
    certbot \
    python3-certbot-nginx

# Configure firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Enable lingering for senex user
loginctl enable-linger senex

# Configure subuid/subgid
echo "senex:100000:65536" >> /etc/subuid
echo "senex:100000:65536" >> /etc/subgid

# Enable unattended upgrades
dpkg-reconfigure -plow unattended-upgrades

echo "System setup complete"
```

**Verification**:
- [ ] Firewall active: `sudo ufw status`
- [ ] Podman installed: `podman --version`
- [ ] Lingering enabled: `loginctl show-user senex | grep Linger`

#### Day 3-4: Ansible Configuration

**Tasks**:
1. Set up Ansible on control machine
2. Create inventory structure
3. Generate secrets
4. Create Ansible Vault

**On control machine**:
```bash
# Install Ansible
pip install ansible

# Create deployment directory
mkdir -p ~/senex-deployment
cd ~/senex-deployment

# Install collections
cat > requirements.yml << EOF
collections:
  - name: containers.podman
    version: ">=1.17.0"
  - name: community.crypto
  - name: ansible.posix
EOF

ansible-galaxy collection install -r requirements.yml

# Create inventory
mkdir -p inventory/production/group_vars

# hosts.yml
cat > inventory/production/hosts.yml << EOF
all:
  children:
    webservers:
      hosts:
        your-domain.com:
          ansible_host: YOUR_SERVER_IP
          ansible_user: senex
EOF

# all.yml (non-sensitive)
cat > inventory/production/group_vars/all.yml << EOF
app_name: senextrader
domain_name: your-domain.com
django_image: YOUR_REGISTRY/senex-trader
django_version: latest
enable_ssl: true
EOF

# Generate secrets
DJANGO_SECRET=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
FERNET_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
DB_PASSWORD=$(openssl rand -base64 24)
REDIS_PASSWORD=$(openssl rand -base64 32)

# Create vault
echo "your-vault-password" > ~/.vault_pass_production
chmod 600 ~/.vault_pass_production

ansible-vault create inventory/production/group_vars/vault.yml \
  --vault-password-file ~/.vault_pass_production

# Paste these values when editor opens:
# vault_secret_key: "$DJANGO_SECRET"
# vault_field_encryption_key: "$FERNET_KEY"
# vault_db_password: "$DB_PASSWORD"
# vault_redis_password: "$REDIS_PASSWORD"
# vault_tastytrade_client_id: "YOUR_CLIENT_ID"
# vault_tastytrade_client_secret: "YOUR_CLIENT_SECRET"
```

**Verification**:
- [ ] Ansible connectivity: `ansible all -i inventory/production/hosts.yml -m ping`
- [ ] Vault accessible: `ansible-vault view inventory/production/group_vars/vault.yml --vault-password-file ~/.vault_pass_production`

#### Day 5: Deploy Infrastructure

**Tasks**:
1. Copy deployment configs to server
2. Create Podman network
3. Deploy Quadlet files

**Copy configurations**:
```bash
# Copy Quadlet files
scp deployment/configs/systemd/*.example senex@SERVER_IP:~/.config/containers/systemd/
rename 's/.example$//' ~/.config/containers/systemd/*.example

# Copy Nginx config
sudo scp deployment/configs/nginx/your-domain.com.conf senex@SERVER_IP:/etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/your-domain.com /etc/nginx/sites-enabled/

# Copy Redis config
scp deployment/configs/redis/redis.conf senex@SERVER_IP:~/senex-trader/configs/
```

**Deploy via Ansible**:
```bash
ansible-playbook -i inventory/production/hosts.yml ansible/site.yml \
  --vault-password-file ~/.vault_pass_production \
  --tags phase1
```

**Verification**:
- [ ] Podman network created: `podman network ls`
- [ ] All Quadlet files present: `ls ~/.config/containers/systemd/`

### Week 2: Application Deployment

#### Day 6-7: Database and Cache

**Tasks**:
1. Start PostgreSQL and Redis
2. Run migrations
3. Create superuser

**Commands**:
```bash
# Reload systemd
systemctl --user daemon-reload

# Start PostgreSQL
systemctl --user start postgres.service

# Verify PostgreSQL
podman exec postgres pg_isready

# Start Redis
systemctl --user start redis.service

# Verify Redis
podman exec redis redis-cli -a PASSWORD ping

# Start Django for migrations
systemctl --user start django.service

# Run migrations
podman exec django python manage.py migrate

# Create superuser
podman exec -it django python manage.py createsuperuser

# Collect static files
podman exec django python manage.py collectstatic --noinput
```

**Verification**:
- [ ] PostgreSQL responding: `podman logs postgres`
- [ ] Redis responding: `podman logs redis`
- [ ] Migrations applied: `podman exec django python manage.py showmigrations`
- [ ] Superuser created: Can login to /admin/

#### Day 8-9: Celery and Application

**Tasks**:
1. Start Celery worker and beat
2. Verify scheduled tasks
3. Test application

**Commands**:
```bash
# Start Celery worker
systemctl --user start celery-worker.service

# Start Celery beat
systemctl --user start celery-beat.service

# Verify workers
podman exec django celery -A senextrader inspect active

# Check scheduled tasks
podman exec django python manage.py shell << EOF
from django_celery_beat.models import PeriodicTask
for task in PeriodicTask.objects.all():
    print(f"{task.name}: {task.enabled}")
EOF
```

**Verification**:
- [ ] Celery worker running: `systemctl --user status celery-worker`
- [ ] Celery beat running: `systemctl --user status celery-beat`
- [ ] Scheduled tasks visible in admin
- [ ] Test task execution: Create manual task and verify completion

#### Day 10: SSL and Nginx

**Tasks**:
1. Request SSL certificate
2. Configure Nginx
3. Test HTTPS

**Commands**:
```bash
# Request certificate
sudo certbot --nginx \
  -d your-domain.com \
  -d www.your-domain.com \
  --agree-tos \
  --email admin@your-domain.com

# Test Nginx config
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx

# Test SSL
curl -I https://your-domain.com
```

**Verification**:
- [ ] SSL certificate installed: `ls /etc/letsencrypt/live/your-domain.com/`
- [ ] HTTPS working: `curl https://your-domain.com/health/`
- [ ] HTTP redirects to HTTPS
- [ ] SSL Labs grade A+: https://www.ssllabs.com/ssltest/

#### Day 11-12: Testing and Validation

**Tasks**:
1. Complete pre-deployment checklist
2. Run health checks
3. Perform functional testing
4. Load testing (optional)

**Checklist validation**:
```bash
# Run health check
/opt/scripts/health-check.sh

# Test WebSocket
# (Open browser console and test WebSocket connection)

# Test TastyTrade integration
# (Login and connect TastyTrade account)

# Test trading functionality
# (Place test order in sandbox mode)
```

**Verification**:
- [ ] All services healthy
- [ ] WebSocket connections working
- [ ] TastyTrade OAuth functional
- [ ] Can execute test trade
- [ ] Celery tasks processing
- [ ] No errors in logs

#### Day 13-14: Go-Live

**Tasks**:
1. Final security review
2. Set up external monitoring
3. Configure backups
4. Go-live

**Final steps**:
```bash
# Set up backups
sudo cp deployment/scripts/backup-*.sh /opt/scripts/
sudo chmod +x /opt/scripts/backup-*.sh

# Schedule backups
crontab -e
# Add:
# 0 2 * * * /opt/scripts/backup-postgresql.sh
# 0 * * * * /opt/scripts/backup-redis.sh

# Set up external monitoring (UptimeRobot)
# Visit uptimerobot.com and add monitor

# Complete go-live checklist
# See: deployment/checklists/go-live-checklist.md
```

**Go-Live**:
- [ ] Complete go-live checklist
- [ ] Announce to users
- [ ] Monitor for 24 hours
- [ ] Document any issues

### Phase 1 Deliverables

Functional single-server deployment
SSL/TLS configured
Basic monitoring (health checks + UptimeRobot)
Daily backups scheduled
All core services running

## Phase 2: Production Ready (Week 3-4)

**Goal**: Separate services, add monitoring
**Cost**: ~$150/month
**Capacity**: 5,000 users, 2,000 trades/day

### Week 3: Service Separation

#### Day 15-16: Additional Servers

**Tasks**:
1. Provision Database server
2. Provision Redis/Celery server
3. Migrate PostgreSQL

**Server setup**:
```bash
# Provision 2 additional servers:
# - db01: PostgreSQL (2 CPU, 4GB RAM)
# - cache01: Redis + Celery (2 CPU, 2GB RAM)

# Configure DNS
# db01.internal.your-domain.com → DB_SERVER_IP
# cache01.internal.your-domain.com → CACHE_SERVER_IP

# Update inventory
cat >> inventory/production/hosts.yml << EOF
database:
  hosts:
    db01.internal.your-domain.com:
      ansible_host: DB_SERVER_IP
      ansible_user: senex

cache:
  hosts:
    cache01.internal.your-domain.com:
      ansible_host: CACHE_SERVER_IP
      ansible_user: senex
EOF
```

#### Day 17-18: PostgreSQL Migration

**Tasks**:
1. Deploy PostgreSQL to db01
2. Backup and migrate data
3. Update Django configuration

**Migration**:
```bash
# On old server: Backup
/opt/scripts/backup-postgresql.sh

# On new db01: Deploy PostgreSQL
ansible-playbook site.yml --tags database --limit database

# Restore backup on new server
scp /var/backups/postgresql/latest.backup.gz db01:/tmp/
ssh db01 "/opt/scripts/restore-postgresql.sh /tmp/latest.backup.gz"

# Update Django env
# Change DB_HOST from 'postgres' to 'db01.internal.your-domain.com'

# Restart Django
systemctl --user restart django celery-worker celery-beat
```

#### Day 19-20: PgBouncer Setup

**Tasks**:
1. Install PgBouncer on db01
2. Configure connection pooling
3. Update Django to use PgBouncer

**See**: [04-SERVICE-CONFIGURATION.md](./04-SERVICE-CONFIGURATION.md#connection-pooling-with-pgbouncer)

### Week 4: Monitoring and Optimization

#### Day 21-22: Prometheus + Grafana

**Tasks**:
1. Deploy Prometheus container
2. Deploy Grafana container
3. Configure Django metrics

**See**: [07-MONITORING-LOGGING.md](./07-MONITORING-LOGGING.md#phase-2-prometheus--grafana)

#### Day 23-24: Dashboards and Alerts

**Tasks**:
1. Import Grafana dashboards
2. Configure alert rules
3. Set up Slack/email notifications

**Dashboards to import**:
- Django: ID 17658
- PostgreSQL: ID 9628
- Redis: ID 11835

#### Day 25-26: Performance Tuning

**Tasks**:
1. Optimize database queries
2. Configure caching
3. Tune PostgreSQL parameters

**Query optimization**:
```sql
-- Enable pg_stat_statements
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Find slow queries
SELECT
    calls,
    mean_exec_time::numeric(10,2) as avg_ms,
    query
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;

-- Add missing indexes
-- (See queries from pg_stat_statements)
```

#### Day 27-28: Validation and Optimization

**Tasks**:
1. Load testing
2. Performance benchmarking
3. Cost optimization review

**Load testing with Locust**:
```python
# locustfile.py
from locust import HttpUser, task, between

class TradingUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def view_positions(self):
        self.client.get("/positions/")

    @task
    def health_check(self):
        self.client.get("/health/")

# Run: locust -f locustfile.py --host=https://your-domain.com
```

### Phase 2 Deliverables

Separated services (Django, PostgreSQL, Redis/Celery)
PgBouncer connection pooling
Prometheus + Grafana monitoring
Performance optimized
Alert rules configured

## Phase 3: High Availability (Week 5-8)

**Goal**: Multi-server redundancy, 99.9% uptime
**Cost**: ~$350/month
**Capacity**: 20,000 users, 10,000 trades/day

### Week 5: Database HA

#### Day 29-32: PostgreSQL Replication

**Tasks**:
1. Set up PostgreSQL replica
2. Configure streaming replication
3. Implement database router

**See**: [09-SCALING-STRATEGY.md](./09-SCALING-STRATEGY.md#postgresql-read-replica)

### Week 6: Redis HA

#### Day 33-36: Redis Sentinel

**Tasks**:
1. Deploy Redis replica servers
2. Configure Sentinel cluster
3. Update Django/Celery configuration

**See**: [09-SCALING-STRATEGY.md](./09-SCALING-STRATEGY.md#redis-sentinel-high-availability)

### Week 7: Application Scaling

#### Day 37-40: Multiple Django Instances

**Tasks**:
1. Deploy additional Django servers
2. Configure load balancer (HAProxy or Nginx)
3. Test failover

**See**: [09-SCALING-STRATEGY.md](./09-SCALING-STRATEGY.md#horizontal-scaling-djangodaphne)

### Week 8: Advanced Monitoring

#### Day 41-44: Log Aggregation

**Tasks**:
1. Deploy Grafana Loki
2. Configure Promtail
3. Create log dashboards

**See**: [07-MONITORING-LOGGING.md](./07-MONITORING-LOGGING.md#phase-3-log-aggregation-with-loki)

#### Day 45-49: Testing and Validation

**Tasks**:
1. Chaos engineering tests
2. Failover drills
3. Performance validation
4. Documentation updates

#### Day 50-56: Production Hardening

**Tasks**:
1. Security audit
2. Backup restoration testing
3. Disaster recovery drill
4. Team training

### Phase 3 Deliverables

PostgreSQL primary + replica
Redis Sentinel cluster
Multiple Django/Daphne instances
Load balancer with health checks
Log aggregation with Loki
99.9% uptime capability
Disaster recovery validated

## Post-Implementation

### Ongoing Tasks

**Daily**:
- Monitor dashboards
- Review error logs
- Check backup status

**Weekly**:
- Review performance metrics
- Security log analysis
- Capacity planning review

**Monthly**:
- Test backup restoration
- Security updates
- Performance optimization

**Quarterly**:
- Disaster recovery drill
- Security audit
- Cost optimization review

### Success Criteria

**Phase 1**:
- [ ] All services running
- [ ] <1% error rate
- [ ] <2s p95 response time
- [ ] SSL A+ rating
- [ ] Daily backups successful

**Phase 2**:
- [ ] Separated services operational
- [ ] Monitoring dashboards active
- [ ] Alerts configured
- [ ] <500ms p95 response time (with optimizations)
- [ ] >99% uptime

**Phase 3**:
- [ ] Redundancy on all critical services
- [ ] Automated failover working
- [ ] <1s p95 response time under load
- [ ] >99.9% uptime
- [ ] Disaster recovery under 30 minutes

## Risk Management

### Common Issues and Solutions

| Risk | Mitigation | Contingency |
|------|------------|-------------|
| DNS propagation delay | Set low TTL (300s) | Use /etc/hosts for testing |
| SSL cert request fails | Use HTTP-01 challenge | Manual certbot standalone |
| Database migration fails | Test in staging first | Rollback with backup |
| High traffic spike | Rate limiting configured | Scale horizontally |
| Service outage | Health checks + auto-restart | Documented recovery procedures |

### Rollback Procedures

**If Phase 1 deployment fails**:
1. Stop all services
2. Restore backups (if data changed)
3. Document issues
4. Fix and retry

**If Phase 2 migration fails**:
1. Restore old database from backup
2. Revert Django configuration
3. Continue on single server
4. Debug migration issues

**If Phase 3 HA fails**:
1. Disable failing components
2. Run on Phase 2 configuration
3. Investigate and fix
4. Retry implementation

## Timeline Summary

| Phase | Duration | Cost/Month | Capacity |
|-------|----------|------------|----------|
| Phase 1 | 2 weeks | $50 | 1K users |
| Phase 2 | 2 weeks | $150 | 5K users |
| Phase 3 | 4 weeks | $350 | 20K users |
| **Total** | **8 weeks** | **Scales** | **Scales** |

## Next Actions

1. Review all deployment documentation
2. Complete Phase 1 Day 1 tasks
3. Track progress against timeline
4. Document deviations and learnings
