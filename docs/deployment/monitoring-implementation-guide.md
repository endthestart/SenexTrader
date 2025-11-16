# Senex Trader Production Monitoring Setup

This document describes the monitoring and alerting infrastructure for Senex Trader production.

## Overview

The monitoring system consists of three layers:

1. **Email Alerts** - Django's AdminEmailHandler sends emails on ERROR-level events
2. **Watchdog Service** - Local health check that auto-restarts unresponsive web service
3. **Auto-Restart** - Systemd configuration for automatic recovery

## 1. Email Alerts (Django AdminEmailHandler)

### What It Does
- Automatically sends emails when ERROR or CRITICAL log events occur
- Includes full stack traces and request details
- Filters sensitive data (tokens, passwords) before sending

### Configuration Required

Email alerts are configured via Ansible vault. Edit `deployment/ansible/inventory/production-vault.yml`:

```yaml
# Email Configuration (Production)
email_backend: "django.core.mail.backends.smtp.EmailBackend"
email_host: "smtp.gmail.com"  # Or your SMTP server
email_port: 587
email_use_tls: "true"
email_host_user: "noreply@your-domain.com"
email_host_password: "YOUR-APP-PASSWORD"  # For Gmail: Use App Password, not regular password
default_from_email: "Senex Trader <noreply@your-domain.com>"
admin_email: "your-email@example.com"  # YOUR email address for alerts
server_email: "errors@your-domain.com"
```

### Gmail App Password Setup

If using Gmail:

1. Go to Google Account → Security → 2-Step Verification
2. At the bottom, select "App passwords"
3. Generate new app password for "Mail"
4. Use this 16-character password in `email_host_password`

### Testing Email Alerts

After deployment, test from the server:

```bash
# SSH to production server
ssh root@your-domain.com

# Test email from Django shell
su - senex -c "cd /app && python manage.py shell -c \"
from django.core.mail import mail_admins
mail_admins('Test Alert', 'This is a test alert from Senex Trader')
\""
```

You should receive an email at your configured `admin_email` address.

## 2. Watchdog Service (Auto-Restart)

### What It Does
The watchdog service monitors the web application health and automatically restarts it if unresponsive.

**Features:**
- Checks `/health/simple/` endpoint every 60 seconds
- Restarts web service after 3 consecutive failures (3 minutes)
- Sends email notification on restart
- Logs all actions to `/var/log/senex_trader/watchdog.log`

**Files:**
- Script: `/opt/senex-trader/scripts/senex-watchdog.py`
- Service: `/etc/systemd/system/senex-watchdog.service`
- Timer: `/etc/systemd/system/senex-watchdog.timer`
- State: `/var/lib/senex-watchdog/failures.txt`

### How It Works

1. **Every minute**, systemd timer triggers watchdog service
2. Watchdog attempts HTTP GET to `http://localhost:8000/health/simple/`
3. If successful: resets failure counter
4. If failed: increments failure counter
5. After **3 consecutive failures**:
   - Restarts web.service via `systemctl --machine=senex@ --user restart web.service`
   - Waits 10 seconds for service to start
   - Verifies service is healthy
   - Sends email notification to admins

### Manual Operations

```bash
# Check watchdog status
sudo systemctl status senex-watchdog.timer
sudo systemctl list-timers senex-watchdog.timer

# View watchdog logs
sudo tail -f /var/log/senex_trader/watchdog.log

# Check failure count
cat /var/lib/senex-watchdog/failures.txt

# Manually trigger watchdog check (for testing)
sudo systemctl start senex-watchdog.service

# Disable watchdog (not recommended)
sudo systemctl stop senex-watchdog.timer
sudo systemctl disable senex-watchdog.timer

# Re-enable watchdog
sudo systemctl enable senex-watchdog.timer
sudo systemctl start senex-watchdog.timer
```

## 3. Systemd Auto-Restart

The web service itself is configured to automatically restart on failure.

**Configuration** (in `/opt/senex-trader/.config/systemd/user/web.service.d/override.conf`):

```ini
[Service]
Restart=on-failure        # Restart if process exits with non-zero code
RestartSec=10s            # Wait 10 seconds before restart
StartLimitBurst=5         # Max 5 restart attempts
StartLimitIntervalSec=600 # Within 10 minutes
```

This provides an additional layer of recovery if the process crashes (vs. hanging).

## Monitoring Stack Summary

| Layer | Purpose | Trigger | Action |
|-------|---------|---------|--------|
| **Django Logging** | Detect application errors | ERROR/CRITICAL log events | Send email to admins |
| **Watchdog Service** | Detect hung process | Health check fails 3x | Restart service + email |
| **Systemd Auto-Restart** | Recover from crashes | Process exits with error | Restart service |

## Deployment

The monitoring stack is automatically deployed when you run the Ansible playbook:

```bash
cd deployment/ansible

# Production deployment (includes monitoring)
ansible-playbook deploy.yml --limit production --ask-vault-pass
```

This will:
1. Deploy watchdog script and systemd files
2. Configure email environment variables from vault
3. Update web service with auto-restart configuration
4. Enable and start watchdog timer

## Post-Deployment Verification

After deployment, verify all monitoring is working:

```bash
# SSH to production
ssh root@your-domain.com

# 1. Check watchdog timer is active
systemctl list-timers senex-watchdog.timer

# 2. Check web service has auto-restart configured
systemctl --machine=senex@ --user show web.service | grep -E 'Restart=|RestartSec='

# 3. Test email configuration
su - senex -c "cd /app && python manage.py shell -c \"
from django.core.mail import mail_admins
mail_admins('Production Monitoring Test', 'Monitoring deployed successfully')
\""

# 4. View recent watchdog checks
tail -20 /var/log/senex_trader/watchdog.log
```

## What Notifications You'll Receive

### Regular Email Alerts
You'll receive emails for:
- **Application errors** (500 errors, exceptions, critical events)
- **Security events** (failed authentication attempts, etc.)
- **Service restarts** (when watchdog restarts the web service)

### Log-Only Events
These events are logged but don't trigger emails:
- INFO/DEBUG level logs
- Successful health checks
- Normal service operations

## Troubleshooting

### No Emails Received

1. **Check email configuration**:
   ```bash
   ssh root@your-domain.com
   cat /etc/containers/systemd/.env | grep EMAIL
   ```

2. **Check Django can send email**:
   ```bash
   su - senex -c "cd /app && python manage.py shell -c \"
   from django.core.mail import send_mail
   send_mail('Test', 'Body', 'noreply@your-domain.com', ['your-email@example.com'])
   \""
   ```

3. **Check application logs**:
   ```bash
   tail -50 /opt/senex-trader/data/logs/errors.log
   ```

### Watchdog Not Running

```bash
# Check timer status
systemctl status senex-watchdog.timer

# Check service status
systemctl status senex-watchdog.service

# View recent logs
journalctl -u senex-watchdog.service -n 50
```

### Too Many Restart Emails

If the watchdog is restarting the service too frequently:

1. **Investigate root cause** - check application logs
2. **Temporarily increase failure threshold** - edit `/opt/senex-trader/scripts/senex-watchdog.py`, change `MAX_FAILURES = 3` to higher value
3. **Disable watchdog temporarily**:
   ```bash
   sudo systemctl stop senex-watchdog.timer
   ```

## Best Practices

1. **Test email configuration immediately** after deployment
2. **Monitor watchdog logs** for the first few days to ensure it's working
3. **Don't disable monitoring** unless actively debugging
4. **Investigate restart causes** - if watchdog restarts service, find out why
5. **Keep email credentials secure** - always use Ansible vault

## Related Documentation

- Email settings: `senex_trader/settings/production.py` lines 255-333
- Watchdog script: `deployment/scripts/senex-watchdog.py`
- Ansible deployment: `deployment/ansible/deploy.yml`
- Vault configuration: `deployment/ansible/inventory/production-vault.yml`

## Support

If monitoring isn't working:

1. Check this document first
2. Review logs (watchdog, application, systemd)
3. Test email configuration manually
4. Verify environment variables are set correctly

---

**Last Updated**: 2025-10-27
