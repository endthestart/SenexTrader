# Environment Differences: Staging vs Production

This document tracks configuration differences between staging and production environments to ensure environment-specific settings are properly managed.

## Infrastructure

| Aspect | Staging | Production |
|--------|---------|------------|
| **Server** | 10.0.0.100 (internal) | your-domain.com (public) |
| **User** | root (rootful Podman) | senex (rootless Podman) |
| **Domain** | your-app.example.com | your-domain.com |
| **Nginx** | External proxy at 10.0.0.209 | On same server |
| **SSL/TLS** | Handled by external nginx | Let's Encrypt (Certbot) |
| **Podman Version** | 5.x (Debian 13) | 5.x (Debian 13) |

## Network Configuration

### Staging-Specific

**UFW Rules:**
- Allow Podman internal network: `10.89.0.0/24` (for aardvark-dns)
- Allow route forwarding: `10.0.0.0/24 → port 8000` (for external nginx proxy)

**Why:** Staging uses external nginx proxy at 10.0.0.209 that must forward traffic through UFW's FORWARD chain to reach Podman containers.

**Ansible Condition:**
```yaml
when:
  - django_env == 'staging'
```

### Production-Specific

**UFW Rules:**
- Standard firewall: ports 22, 80, 443
- No special route rules needed (nginx on same host)

**SSL Configuration:**
- Nginx handles SSL termination
- Certbot automatic renewal
- HTTPS redirect enforced

**Ansible Condition:**
```yaml
when:
  - django_env == 'production'
  - enable_ssl | default(false)
```

## Application Settings

### Django Settings Files

| Setting | Staging | Production |
|---------|---------|------------|
| **Settings Module** | `senex_trader.settings.staging` | `senex_trader.settings.production` |
| **ALLOWED_HOSTS** | `your-app.example.com,10.0.0.100,localhost,127.0.0.1` | `your-domain.com,www.your-domain.com` |
| **WS_ALLOWED_ORIGINS** | `https://your-app.example.com` | `https://your-domain.com,https://www.your-domain.com` |
| **APP_BASE_URL** | `https://your-app.example.com` | `https://your-domain.com` |
| **SECURE_SSL_REDIRECT** | False (nginx handles) | True |
| **SECURE_PROXY_SSL_HEADER** | `("HTTP_X_FORWARDED_PROTO", "https")` | Not set |

### Container Configuration

| Service | Staging | Production |
|---------|---------|------------|
| **Container Names** | `postgres`, `redis`, `web`, `celery_worker`, `celery_beat` | Same |
| **Network** | `senex_network` (10.89.0.0/24) | Same |
| **Exposed Ports** | 8000 (HTTP) | 8000 (behind nginx) |
| **Image Tag** | v0.1.16 | v0.1.16 (same) |

## Deployment Differences

### Staging Deployment

```bash
ansible-playbook deploy.yml --limit staging --ask-vault-pass
```

**Unique Steps:**
1. Creates UFW route rule for external nginx (10.0.0.0/24)
2. Uses rootful Podman (root user)
3. No SSL configuration (handled externally)

### Production Deployment

```bash
ansible-playbook deploy.yml --limit production --ask-vault-pass
```

**Unique Steps:**
1. Creates non-root user (`senex`)
2. Installs nginx on same server
3. Obtains Let's Encrypt SSL certificate
4. Configures HTTPS redirect

## Common Issues

### Staging-Only Issues

**Problem:** Nginx proxy at 10.0.0.209 cannot reach application
- **Cause:** Missing UFW route rule for 10.0.0.0/24
- **Solution:** `ufw route allow from 10.0.0.0/24 to any port 8000`
- **Ansible:** Automatically applied when `django_env == 'staging'`

**Problem:** DNS resolution fails between containers
- **Cause:** UFW blocking Podman internal network (10.89.0.0/24)
- **Solution:** `ufw allow from 10.89.0.0/24`
- **Ansible:** Automatically applied for all environments

### Production-Only Issues

**Problem:** SSL certificate renewal fails
- **Cause:** Certbot cron job not running
- **Solution:** `systemctl status certbot.timer` and renew manually
- **N/A for staging:** External nginx handles SSL

**Problem:** Rootless Podman port binding fails
- **Cause:** Unprivileged user cannot bind to port 8000
- **Solution:** Use port > 1024 or configure nginx to proxy
- **N/A for staging:** Uses rootful Podman

## Testing After Changes

### Verify Staging

```bash
# From control machine
curl -I http://10.0.0.100:8000/health/

# Via nginx proxy
curl -I https://your-app.example.com/health/
```

### Verify Production

```bash
# Direct to server
ssh senex@your-domain.com
curl -I http://localhost:8000/health/

# Via nginx (HTTPS)
curl -I https://your-domain.com/health/
```

## Maintenance Notes

**When adding environment-specific configuration:**

1. Update this document with the difference
2. Add Ansible conditional: `when: django_env == 'staging'` or `'production'`
3. Test on staging first
4. Document rollback procedure
5. Deploy to production only after staging verification

**When changing common configuration:**

1. Verify impact on both environments
2. Update inventory files (`hosts.yml`) if needed
3. Update vault files if secrets change
4. Test on staging, then production

## Related Files

- **Ansible Inventory:** `deployment/ansible/inventory/hosts.yml`
- **Staging Vault:** `deployment/ansible/inventory/staging-vault.yml` (encrypted)
- **Production Vault:** `deployment/ansible/inventory/production-vault.yml` (encrypted)
- **Main Playbook:** `deployment/ansible/deploy.yml`
- **Django Settings:** `senex_trader/settings/{staging,production}.py`

---

**Last Updated:** 2025-10-15
**Maintained By:** Deployment team
**Review Frequency:** After each environment-specific change
