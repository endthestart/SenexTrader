# Security Hardening

## Security Checklist Overview

This guide provides comprehensive security hardening procedures for production deployment. All items should be completed before go-live.

**Security Principles**:
- Defense in depth (multiple security layers)
- Principle of least privilege
- Fail securely (secure defaults)
- Keep security simple
- Assume breach (monitoring and detection)

## Critical Vulnerabilities to Address

### CVE-2025-49844: Redis Unauthenticated Access (CVSS 10.0)

**Vulnerability**: Redis instances without authentication allow remote code execution.

**Mitigation** (CRITICAL):

1. **Require authentication**:
```conf
# In redis.conf
requirepass STRONG_PASSWORD_HERE

# Or via command line
Exec=redis-server --requirepass ${REDIS_PASSWORD}
```

2. **Bind to localhost only** (if not using Podman network):
```conf
bind 127.0.0.1
```

3. **Disable dangerous commands**:
```conf
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command KEYS ""
rename-command CONFIG ""
```

4. **Verify protection**:
```bash
# Should fail without password
podman exec redis redis-cli PING
# Expected: (error) NOAUTH Authentication required

# Should work with password
podman exec redis redis-cli -a PASSWORD PING
# Expected: PONG
```

**Status Check**:
```bash
# Test from outside container
redis-cli -h SERVER_IP ping
# Should timeout or return connection refused
```

## System-Level Security

### SSH Hardening

**File**: `/etc/ssh/sshd_config`

```bash
# Disable root login
PermitRootLogin no

# Key-only authentication
PasswordAuthentication no
PubkeyAuthentication yes

# Disable empty passwords
PermitEmptyPasswords no

# Limit user access
AllowUsers senex

# Change default port (optional but recommended)
Port 2222

# Disable X11 forwarding
X11Forwarding no

# Set strict modes
StrictModes yes

# Limit authentication attempts
MaxAuthTries 3
MaxSessions 2

# Use Protocol 2 only
Protocol 2
```

**Apply changes**:
```bash
sudo sshd -t  # Test configuration
sudo systemctl reload sshd
```

**SSH Key Setup**:
```bash
# On your local machine
ssh-keygen -t ed25519 -C "admin@your-domain.com"

# Copy to server
ssh-copy-id -i ~/.ssh/id_ed25519.pub senex@SERVER_IP

# Test key-based login
ssh -i ~/.ssh/id_ed25519 senex@SERVER_IP

# Disable password auth only after confirming key works!
```

### Fail2ban Configuration

**Install**:
```bash
sudo apt install fail2ban
```

**Configuration** (`/etc/fail2ban/jail.local`):
```ini
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
destemail = admin@your-domain.com
sendername = Fail2Ban
action = %(action_mwl)s

[sshd]
enabled = true
port = 22
logpath = /var/log/auth.log
maxretry = 3
bantime = 86400

[nginx-http-auth]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log

[nginx-limit-req]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 10

[nginx-botsearch]
enabled = true
port = http,https
logpath = /var/log/nginx/access.log
maxretry = 2
```

**Start and enable**:
```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Check status
sudo fail2ban-client status
sudo fail2ban-client status sshd
```

### Automatic Security Updates

**Ubuntu/Debian**:
```bash
# Install
sudo apt install unattended-upgrades

# Configure
sudo dpkg-reconfigure -plow unattended-upgrades

# Edit config
sudo nano /etc/apt/apt.conf.d/50unattended-upgrades
```

**Configuration**:
```
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
};

Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Mail "admin@your-domain.com";
```

### SELinux/AppArmor

**Ubuntu (AppArmor)**:
```bash
# Check status
sudo aa-status

# Install tools
sudo apt install apparmor-utils

# Enable if disabled
sudo systemctl enable apparmor
sudo systemctl start apparmor
```

**RHEL/Rocky (SELinux)**:
```bash
# Check status
getenforce
# Should return: Enforcing

# If Permissive, enable enforcing
sudo setenforce 1

# Make permanent
sudo sed -i 's/SELINUX=permissive/SELINUX=enforcing/' /etc/selinux/config

# Check for denials
sudo ausearch -m avc -ts recent
```

**Podman with SELinux**:
```bash
# Verify SELinux labels on volumes
podman volume inspect postgres_data | grep -i selinux

# Correct labels if needed
podman volume create postgres_data --opt o=Z
```

## Container Security

### Rootless Podman Verification

```bash
# Verify running as non-root user
podman ps --format "{{.Names}}: User={{.User}}"

# Should show: postgres: User=senex (not root)

# Check user namespace
podman unshare cat /proc/self/uid_map
# Should show: 0   1000    1 (or similar non-zero UID)

# Verify lingering enabled
loginctl show-user senex | grep Linger
# Should show: Linger=yes
```

### Container Security Options

**Add to Quadlet files**:
```ini
[Container]
# Drop all capabilities
SecurityLabelDisable=false
NoNewPrivileges=true

# Read-only root filesystem (where possible)
ReadOnlyRootfs=true

# Specific capability requirements (if needed)
AddCapability=NET_BIND_SERVICE  # Only if binding to port <1024

# Seccomp profile
SeccompProfile=/usr/share/containers/seccomp.json
```

### Image Security

**Scan images for vulnerabilities**:
```bash
# Install Trivy
sudo apt install wget apt-transport-https gnupg lsb-release
wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
echo "deb https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee -a /etc/apt/sources.list.d/trivy.list
sudo apt update
sudo apt install trivy

# Scan Django image
trivy image registry.example.com/senex-trader:latest

# Scan for HIGH and CRITICAL only
trivy image --severity HIGH,CRITICAL registry.example.com/senex-trader:latest
```

**Docker Content Trust** (if using Docker registry):
```bash
export DOCKER_CONTENT_TRUST=1
docker pull registry.example.com/senex-trader:latest
```

## Application Security

### Django Security Settings

**Verify in production.py**:
```python
# CRITICAL: Ensure these are set correctly
DEBUG = False
SECRET_KEY = os.environ.get('SECRET_KEY')  # From Ansible Vault
ALLOWED_HOSTS = ['your-domain.com', 'www.your-domain.com']

# Security headers
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# HSTS
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# CSRF
CSRF_COOKIE_HTTPONLY = True
CSRF_USE_SESSIONS = True
CSRF_COOKIE_SAMESITE = 'Strict'

# Session security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 3600  # 1 hour

# Content Security Policy
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")  # Adjust as needed
```

**Check configuration**:
```bash
podman exec django python manage.py check --deploy
```

### Database Security

**PostgreSQL password strength**:
```bash
# Generate strong password (24+ characters)
openssl rand -base64 24
```

**Restrict database user privileges**:
```sql
-- Connect as postgres superuser
podman exec -it postgres psql -U postgres

-- Revoke unnecessary privileges
REVOKE ALL ON DATABASE senex_trader FROM PUBLIC;
GRANT CONNECT ON DATABASE senex_trader TO senex_user;

-- Grant only needed privileges
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO senex_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO senex_user;

-- Prevent privilege escalation
ALTER USER senex_user WITH NOCREATEDB NOCREATEROLE NOREPLICATION;
```

**Enable SSL connections**:
```sql
-- Verify SSL is enabled
SHOW ssl;

-- Require SSL for user
ALTER USER senex_user REQUIRE SSL;

-- Check connections
SELECT datname, usename, ssl, client_addr FROM pg_stat_ssl
JOIN pg_stat_activity ON pg_stat_ssl.pid = pg_stat_activity.pid;
```

### API Security

**TastyTrade OAuth Token Protection**:

1. **Store tokens encrypted** (already implemented):
```python
from encrypted_model_fields.fields import EncryptedCharField

class TradingAccount(models.Model):
    oauth_token = EncryptedCharField(max_length=512)
    refresh_token = EncryptedCharField(max_length=512)
```

2. **Implement token refresh**:
```python
# In services/brokers/tastytrade_session.py
def refresh_token_if_needed(self):
    if self.token_expires_soon():
        self.refresh_access_token()
```

3. **Rate limiting**:
```python
# In settings/production.py
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'

# In views
from django_ratelimit.decorators import ratelimit

@ratelimit(key='user', rate='5/m', method='POST')
def execute_trade(request):
    # ...
```

### WebSocket Security

**Origin validation** (already in asgi.py):
```python
from channels.security.websocket import AllowedHostsOriginValidator

application = ProtocolTypeRouter({
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
```

**Additional WebSocket security**:
```python
# In streaming/consumers.py
class StreamingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Require authentication
        if not self.scope["user"].is_authenticated:
            await self.close()
            return

        # Rate limit connections
        # Implement connection counting per user

        await self.accept()
```

## Network Security

### Firewall Rules (UFW)

```bash
# Reset if needed
sudo ufw --force reset

# Default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH (change port if modified)
sudo ufw allow 22/tcp comment 'SSH'

# HTTP/HTTPS
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'

# Rate limiting for SSH
sudo ufw limit 22/tcp comment 'SSH rate limit'

# Allow from specific IPs only (optional)
# sudo ufw allow from 203.0.113.0/24 to any port 22

# Enable firewall
sudo ufw enable

# Verify
sudo ufw status numbered
```

### Port Exposure Audit

```bash
# Check listening ports
sudo ss -tulpn | grep LISTEN

# Expected ports:
# 22   - SSH
# 80   - Nginx HTTP
# 443  - Nginx HTTPS
# 127.0.0.1:5432  - PostgreSQL (local only)
# 127.0.0.1:6379  - Redis (local only)
# 127.0.0.1:8000  - Django (local only)

# Close any unexpected ports
```

### Network Segmentation

**Podman network isolation**:
```bash
# Application network (already created)
podman network create senex_net --internal=false

# Optional: Create separate internal network for DB
podman network create senex_db_net --internal=true
# Then connect only PostgreSQL and Redis to this network
```

## Secrets Management Security

### Ansible Vault Security

**Vault password strength**:
```bash
# Generate strong vault password
openssl rand -base64 32
```

**Vault file permissions**:
```bash
chmod 600 ~/.vault_pass_production
chmod 600 inventory/production/group_vars/vault.yml
```

**Audit vault access**:
```bash
# Log all vault operations
alias ansible-vault='{ echo "[$(date)] Vault accessed by $USER" >> /var/log/ansible-vault.log; } && ansible-vault'
```

### Environment File Security

```bash
# Secure .env file
chmod 600 /etc/senex-trader/.env
chown senex:senex /etc/senex-trader/.env

# Verify no secrets in git
git secrets --scan
# Or manually:
grep -r "SECRET_KEY\|PASSWORD\|API_KEY" . --exclude-dir=.git
```

### Key Rotation Schedule

| Secret | Rotation Frequency | Priority |
|--------|-------------------|----------|
| Django SECRET_KEY | Annually | Medium |
| FIELD_ENCRYPTION_KEY | Never (breaks data) | N/A |
| Database passwords | Quarterly | High |
| Redis password | Quarterly | High |
| TastyTrade OAuth | On compromise | Critical |
| SSL certificates | Auto (Let's Encrypt) | Automated |
| Ansible Vault password | Semi-annually | High |

## Monitoring and Detection

### Security Logging

**Enable audit logging**:
```bash
# Install auditd
sudo apt install auditd

# Add rules
sudo auditctl -w /etc/senex-trader/.env -p wa -k secrets_access
sudo auditctl -w /etc/ssh/sshd_config -p wa -k sshd_config_change

# Make persistent
sudo sh -c 'auditctl -l >> /etc/audit/rules.d/senex-trader.rules'

# Search audit logs
sudo ausearch -k secrets_access
```

### Failed Login Monitoring

```bash
# Monitor SSH failed logins
sudo journalctl -u ssh -g "Failed password"

# Monitor Nginx auth failures
sudo grep "401\|403" /var/log/nginx/access.log

# Monitor Django login failures
podman logs django | grep "login failed"
```

### Intrusion Detection

**AIDE (Advanced Intrusion Detection Environment)**:
```bash
# Install
sudo apt install aide

# Initialize database
sudo aideinit

# Check for changes
sudo aide --check

# Update database after legitimate changes
sudo aide --update
```

## Compliance and Auditing

### SOC 2 Type II Requirements

**Access Control**:
- [ ] Multi-factor authentication implemented
- [ ] Role-based access control (RBAC)
- [ ] Audit logs for all access
- [ ] Regular access reviews

**Change Management**:
- [ ] All changes via version control (Git)
- [ ] Change approval process
- [ ] Deployment logging
- [ ] Rollback procedures documented

**Data Protection**:
- [ ] Encryption at rest (PostgreSQL, backups)
- [ ] Encryption in transit (TLS)
- [ ] Data retention policies
- [ ] Secure data deletion

**Monitoring**:
- [ ] Security event logging
- [ ] Alerting for anomalies
- [ ] Log retention (90+ days)
- [ ] Incident response procedures

### Security Audit Checklist

**Monthly**:
- [ ] Review user access and permissions
- [ ] Check for failed login attempts
- [ ] Review firewall logs
- [ ] Update security software
- [ ] Scan for vulnerabilities (Trivy)

**Quarterly**:
- [ ] Rotate database and Redis passwords
- [ ] Review and update security policies
- [ ] Penetration testing (if budget allows)
- [ ] Audit Ansible Vault access

**Annually**:
- [ ] Rotate Django SECRET_KEY
- [ ] Full security audit
- [ ] Disaster recovery drill
- [ ] Security training for team

## Security Testing

### Vulnerability Scanning

**Nmap scan** (external):
```bash
# From external machine
nmap -sV -p 22,80,443 your-domain.com

# Expected: Only 22, 80, 443 open
# All others should be filtered/closed
```

**Nikto web scanner**:
```bash
sudo apt install nikto
nikto -h https://your-domain.com
```

### Penetration Testing

**OWASP ZAP**:
```bash
# Install
sudo apt install zaproxy

# Run automated scan
zap-cli quick-scan https://your-domain.com
```

**Manual testing checklist**:
- [ ] SQL injection (try in all form fields)
- [ ] XSS attacks (try script injection)
- [ ] CSRF token validation
- [ ] Authentication bypass attempts
- [ ] Session hijacking
- [ ] Path traversal
- [ ] File upload vulnerabilities

### SSL/TLS Testing

**SSL Labs**:
```
Visit: https://www.ssllabs.com/ssltest/analyze.html?d=your-domain.com
Target Grade: A or A+
```

**testssl.sh**:
```bash
# Install
git clone https://github.com/drwetter/testssl.sh.git
cd testssl.sh

# Test
./testssl.sh https://your-domain.com
```

## Incident Response

### Security Incident Procedure

**Detection**:
1. Monitor alerts (fail2ban, audit logs, Sentry)
2. Review unusual activity (large traffic spikes, failed logins)
3. User reports

**Containment**:
1. Identify affected systems
2. Isolate compromised containers/servers
3. Block malicious IPs
4. Disable compromised accounts

**Eradication**:
1. Identify root cause
2. Patch vulnerabilities
3. Rotate all credentials
4. Rebuild compromised containers

**Recovery**:
1. Restore from clean backups
2. Verify system integrity
3. Monitor for reinfection
4. Gradually restore service

**Lessons Learned**:
1. Document incident timeline
2. Identify gaps in security
3. Update procedures
4. Implement preventive measures

### Emergency Contacts

```
Security Team Lead: [NAME] - [PHONE] - [EMAIL]
System Administrator: [NAME] - [PHONE] - [EMAIL]
Incident Response: [VENDOR] - [PHONE] - [EMAIL]
```

## Security Documentation

### Required Documentation

**Security Policies**:
- Password policy
- Access control policy
- Incident response plan
- Data classification policy
- Acceptable use policy

**Procedures**:
- Server hardening checklist
- Vulnerability management
- Backup and recovery
- Security patching

**Evidence**:
- Security audit logs
- Vulnerability scan reports
- Penetration test results
- Training records

## Post-Deployment Security Validation

### Go-Live Security Checklist

**Before go-live**:
- [ ] All services using rootless Podman
- [ ] Redis authentication enabled
- [ ] PostgreSQL SSL enforced
- [ ] Firewall configured (only 22, 80, 443)
- [ ] SSH hardened (key-only auth)
- [ ] Fail2ban active
- [ ] Unattended upgrades enabled
- [ ] SELinux/AppArmor enforcing
- [ ] Secrets in Ansible Vault
- [ ] SSL certificate installed
- [ ] Django DEBUG=False
- [ ] ALLOWED_HOSTS set correctly
- [ ] Security headers enabled
- [ ] Rate limiting configured
- [ ] Vulnerability scan passed
- [ ] SSL Labs grade A+
- [ ] No critical findings in security audit

### Continuous Security

**Automated checks** (daily):
```bash
#!/bin/bash
# /opt/scripts/security-check.sh

# Check for failed logins
fail2ban-client status | grep -q "Currently banned: 0" || echo "ALERT: Banned IPs detected"

# Check service status
for service in postgres redis django celery-worker; do
    podman ps | grep -q $service || echo "ALERT: $service not running"
done

# Check SSL expiration
days_until_expiry=$((($(date -d "$(openssl x509 -enddate -noout -in /etc/letsencrypt/live/your-domain.com/cert.pem | cut -d= -f2)" +%s) - $(date +%s)) / 86400))
[ $days_until_expiry -lt 30 ] && echo "ALERT: SSL cert expires in $days_until_expiry days"

# Check disk space
df -h / | awk 'NR==2 {if (substr($5,1,length($5)-1) > 80) print "ALERT: Disk usage " $5}'
```

**Schedule**:
```bash
# Add to cron
0 */6 * * * /opt/scripts/security-check.sh | mail -s "Security Check" admin@your-domain.com
```

## Next Steps

1. **[Set up monitoring and logging](./07-MONITORING-LOGGING.md)**
2. **[Configure backup and disaster recovery](./08-BACKUP-DISASTER-RECOVERY.md)**
3. **[Plan scaling strategy](./09-SCALING-STRATEGY.md)**
