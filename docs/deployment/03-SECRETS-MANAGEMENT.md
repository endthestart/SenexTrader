# Secrets Management

## Overview

All sensitive credentials are managed using **Ansible Vault** with environment-specific encryption. Secrets are never committed unencrypted to version control.

## Encryption Key Generation

### Django SECRET_KEY

```bash
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

### FIELD_ENCRYPTION_KEY (Fernet)

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

### Redis Password

```bash
openssl rand -base64 32
```

### Database Password

```bash
openssl rand -base64 24
```

## Ansible Vault Setup

### Create Vault Password Files

```bash
# Create secure password files (never commit these!)
echo "your-strong-staging-password" > ~/.vault_pass_staging
echo "your-strong-production-password" > ~/.vault_pass_production

# Secure permissions
chmod 600 ~/.vault_pass_*

# Add to .gitignore
echo ".vault_pass_*" >> ~/.gitignore
```

### Create Encrypted Vault Files

**Production Secrets**:
```bash
ansible-vault create inventory/production/group_vars/vault.yml \
  --vault-id production@~/.vault_pass_production
```

**Content** (paste when editor opens):
```yaml
# Django Core
vault_secret_key: "GENERATED-DJANGO-SECRET-KEY"
vault_field_encryption_key: "GENERATED-FERNET-KEY"

# Database
vault_db_name: senextrader
vault_db_user: senex_user
vault_db_password: "GENERATED-DB-PASSWORD"
vault_db_host: postgres
vault_db_port: 5432

# Redis
vault_redis_password: "GENERATED-REDIS-PASSWORD"
vault_redis_url: "redis://:GENERATED-REDIS-PASSWORD@redis:6379"

# Celery
vault_celery_broker_url: "redis://:GENERATED-REDIS-PASSWORD@redis:6379/2"
vault_celery_result_backend: "redis://:GENERATED-REDIS-PASSWORD@redis:6379/3"

# TastyTrade API
vault_tastytrade_client_id: "YOUR-CLIENT-ID"
vault_tastytrade_client_secret: "YOUR-CLIENT-SECRET"
vault_tastytrade_base_url: "https://api.tastyworks.com"

# Email (optional)
vault_email_host: "smtp.gmail.com"
vault_email_port: 587
vault_email_host_user: "noreply@your-domain.com"
vault_email_host_password: "APP-SPECIFIC-PASSWORD"
vault_default_from_email: "noreply@your-domain.com"

# Monitoring (optional)
vault_sentry_dsn: "https://...@sentry.io/..."

# Backup Storage (S3-compatible)
vault_backup_access_key: "S3-ACCESS-KEY"
vault_backup_secret_key: "S3-SECRET-KEY"
vault_backup_bucket: "senex-backups-production"
vault_backup_endpoint: "https://s3.us-east-1.amazonaws.com"
```

**Staging Secrets**:
```bash
ansible-vault create inventory/staging/group_vars/vault.yml \
  --vault-id staging@~/.vault_pass_staging
```

## Vault Operations

### View Encrypted File

```bash
ansible-vault view inventory/production/group_vars/vault.yml \
  --vault-id production@~/.vault_pass_production
```

### Edit Encrypted File

```bash
ansible-vault edit inventory/production/group_vars/vault.yml \
  --vault-id production@~/.vault_pass_production
```

### Encrypt Existing File

```bash
ansible-vault encrypt inventory/production/group_vars/vault.yml \
  --vault-id production@~/.vault_pass_production
```

### Decrypt for Inspection (temporary)

```bash
ansible-vault decrypt inventory/production/group_vars/vault.yml \
  --vault-id production@~/.vault_pass_production
# REMEMBER TO RE-ENCRYPT IMMEDIATELY
ansible-vault encrypt inventory/production/group_vars/vault.yml \
  --vault-id production@~/.vault_pass_production
```

### Change Vault Password

```bash
ansible-vault rekey inventory/production/group_vars/vault.yml \
  --vault-id production@~/.vault_pass_production
```

## Podman Secrets (Alternative Approach)

For enhanced security, use Podman secrets instead of environment variables:

### Create Podman Secret

```bash
# As the app user (senex)
echo "GENERATED-DB-PASSWORD" | podman secret create db_password -
echo "GENERATED-REDIS-PASSWORD" | podman secret create redis_password -
echo "GENERATED-SECRET-KEY" | podman secret create django_secret_key -
```

### Use in Quadlet Files

```ini
[Container]
Secret=db_password,type=env,target=DB_PASSWORD
Secret=redis_password,type=env,target=REDIS_PASSWORD
Secret=django_secret_key,type=env,target=SECRET_KEY
```

### Ansible Task to Create Secrets

```yaml
- name: Create Podman secrets
  containers.podman.podman_secret:
    name: "{{ item.name }}"
    data: "{{ item.value }}"
    state: present
  loop:
    - { name: 'db_password', value: '{{ vault_db_password }}' }
    - { name: 'redis_password', value: '{{ vault_redis_password }}' }
    - { name: 'django_secret_key', value: '{{ vault_secret_key }}' }
  no_log: yes
```

## Environment Variable Reference

Complete list of environment variables used by Senex Trader:

### Core Django Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `DJANGO_SETTINGS_MODULE` | Settings module | `senextrader.settings.production` |
| `SECRET_KEY` | Django secret key | From vault |
| `FIELD_ENCRYPTION_KEY` | Fernet encryption key | From vault |
| `ALLOWED_HOSTS` | Comma-separated domains | `your-domain.com,api.your-domain.com` |
| `DEBUG` | Debug mode (never True in prod) | `False` |

### Database

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_NAME` | Database name | `senextrader` |
| `DB_USER` | Database user | `senex_user` |
| `DB_PASSWORD` | Database password | From vault |
| `DB_HOST` | Database host | `postgres` (container name) |
| `DB_PORT` | Database port | `5432` |

### Redis

| Variable | Description | Example |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection string | `redis://:PASSWORD@redis:6379/0` |

### Celery

| Variable | Description | Example |
|----------|-------------|---------|
| `CELERY_BROKER_URL` | Celery broker | `redis://:PASSWORD@redis:6379/2` |
| `CELERY_RESULT_BACKEND` | Result backend | `redis://:PASSWORD@redis:6379/3` |

### TastyTrade API

| Variable | Description | Example |
|----------|-------------|---------|
| `TASTYTRADE_CLIENT_ID` | OAuth client ID | From vault |
| `TASTYTRADE_CLIENT_SECRET` | OAuth secret | From vault |
| `TASTYTRADE_BASE_URL` | API endpoint | `https://api.tastyworks.com` |

### WebSocket

| Variable | Description | Example |
|----------|-------------|---------|
| `WS_ALLOWED_ORIGINS` | Allowed WS origins | `your-domain.com,api.your-domain.com` |

### Email (Optional)

| Variable | Description | Example |
|----------|-------------|---------|
| `EMAIL_HOST` | SMTP server | `smtp.gmail.com` |
| `EMAIL_PORT` | SMTP port | `587` |
| `EMAIL_HOST_USER` | SMTP username | `noreply@your-domain.com` |
| `EMAIL_HOST_PASSWORD` | SMTP password | From vault |
| `EMAIL_USE_TLS` | Use TLS | `True` |
| `DEFAULT_FROM_EMAIL` | Default sender | `noreply@your-domain.com` |

### Monitoring (Optional)

| Variable | Description | Example |
|----------|-------------|---------|
| `SENTRY_DSN` | Sentry error tracking | From vault |

## Secret Rotation Procedures

### Rotate Database Password

```bash
# 1. Generate new password
NEW_PASSWORD=$(openssl rand -base64 24)

# 2. Update vault file
ansible-vault edit inventory/production/group_vars/vault.yml

# 3. Update PostgreSQL user password
podman exec -it postgres psql -U postgres -c \
  "ALTER USER senex_user WITH PASSWORD '$NEW_PASSWORD';"

# 4. Redeploy Django and Celery containers
ansible-playbook playbooks/deploy.yml --tags app
```

### Rotate Django SECRET_KEY

**WARNING**: Rotating SECRET_KEY invalidates all sessions and signed data.

```bash
# 1. Generate new key
NEW_KEY=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')

# 2. Update vault
ansible-vault edit inventory/production/group_vars/vault.yml

# 3. Redeploy application
ansible-playbook playbooks/deploy.yml --tags django,celery

# 4. Users will need to log in again
```

### Rotate Redis Password

```bash
# 1. Generate new password
NEW_PASSWORD=$(openssl rand -base64 32)

# 2. Update vault
ansible-vault edit inventory/production/group_vars/vault.yml

# 3. Update Redis config and restart
ansible-playbook playbooks/deploy.yml --tags redis

# 4. Restart dependent services
ansible-playbook playbooks/deploy.yml --tags django,celery
```

## Security Best Practices

### Vault Password Security

- **Never commit** vault password files to version control
- **Use strong passwords**: 32+ characters, random
- **Different passwords** for staging and production
- **Store securely**: Password manager (1Password, Bitwarden)
- **Rotate annually** or after personnel changes

### Secret Access Control

- **Limit access**: Only ops team has vault passwords
- **Audit access**: Log who decrypts vault files
- **Separate environments**: Different credentials for staging/production
- **No secrets in logs**: Use `no_log: yes` in Ansible tasks

### Container Security

- **Rootless Podman**: Never run containers as root
- **Secrets in memory**: Prefer Podman secrets over env vars
- **Read-only filesystems**: Use `:ro` flag for volume mounts where possible
- **Drop capabilities**: Use `--cap-drop=all` unless specific caps needed

### TastyTrade OAuth Security

- **Encrypted storage**: OAuth tokens stored encrypted in PostgreSQL
- **Refresh tokens**: Implement automatic token refresh
- **Rotation monitoring**: Alert on refresh failures
- **Scope limitation**: Request minimal OAuth scopes needed

## Compliance Considerations

### SOC 2 Requirements

- **Encryption at rest**: Vault files encrypted with AES-256
- **Encryption in transit**: TLS for all network communications
- **Access logging**: Audit who accessed secrets
- **Secret rotation**: Documented rotation schedule
- **Backup encryption**: Encrypted backups of vault files

### GDPR/CCPA

- **User data protection**: Encryption keys for PII fields
- **Right to deletion**: Secure key deletion procedures
- **Data minimization**: Only store necessary secrets
- **Breach notification**: Procedures for secret compromise

## Troubleshooting

### "Vault password is required"

```bash
# Ensure vault password file exists and has correct content
cat ~/.vault_pass_production

# Use --ask-vault-pass if file is missing
ansible-playbook playbooks/deploy.yml --ask-vault-pass
```

### "Decryption failed"

```bash
# Wrong password or corrupted file
# Try with different vault ID
ansible-vault view inventory/production/group_vars/vault.yml \
  --vault-id staging@~/.vault_pass_staging

# If corrupted, restore from git history
git checkout HEAD~1 -- inventory/production/group_vars/vault.yml
```

### "Secret not found in container"

```bash
# List all secrets
podman secret ls

# Recreate missing secret
echo "SECRET_VALUE" | podman secret create secret_name -

# Restart container
systemctl --user restart django.service
```

## Next Steps

1. **[Review service configurations](./04-SERVICE-CONFIGURATION.md)** that use these secrets
2. **[Set up SSL/TLS](./05-NETWORKING-SSL.md)** with certificate secrets
3. **[Implement security hardening](./06-SECURITY-HARDENING.md)** checklist
