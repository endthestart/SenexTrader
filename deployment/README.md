# Senex Trader Deployment Guide

**Monorepo Deployment** - All deployment files in this repository, no external config repo needed.

---

## Quick Start

### 1. Initial Setup (One Time)

**Choose your setup path:**

#### Path A: Existing Deployment (Migrating from senextrader_config)
If you have existing configs from a backup or previous deployment:

```bash
# Copy your existing configs to config/ directory
cp -r ~/path/to/config-backup/* config/
# OR if you still have the old senextrader_config repo:
cp -r ~/Development/senextrader_config/* config/

# Verify files are in place
ls config/ansible/inventory/hosts.yml
ls config/ansible/vault/production-vault.yml
```

#### Path B: New Deployment (First Time Setup)
If setting up for the first time, follow these steps in order:

**Step 1: Copy Build Configuration**
```bash
cp .senextrader.json.example .senextrader.json
# Edit .senextrader.json with your container registry details
```

**Step 2: Create Config Directory Structure**
```bash
mkdir -p config/ansible/inventory config/ansible/vault
```

**Step 3: Copy and Configure Inventory**
```bash
cp deployment/ansible/inventory/hosts.yml.example config/ansible/inventory/hosts.yml
# Edit config/ansible/inventory/hosts.yml with your server details:
#   - ansible_host: Your server hostname or IP
#   - domain_name: Your domain name
#   - app_user: User to run containers (typically 'senex' for production)
#   - app_directory: Where to install application (typically '/opt/senex-trader')
```

**Step 4: Copy and Configure Vault Template**
```bash
cp deployment/ansible/inventory/production-vault.yml.example config/ansible/vault/production-vault.yml
# Edit config/ansible/vault/production-vault.yml with your production values:
#   - secret_key: Generate with: python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
#   - field_encryption_key: Generate with: python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
#   - db_password: Strong database password
#   - tastytrade_client_id and tastytrade_client_secret: Your TastyTrade API credentials
#   - gitea_username and gitea_token: Your container registry credentials
```

**Step 5: Set Up Ansible Vault Environment**
```bash
# Create vault password file
nano ~/.ansible_vault_pass
# Enter your vault password, save and exit

# Secure the password file
chmod 600 ~/.ansible_vault_pass

# Set environment variables (for fish shell)
set -gx ANSIBLE_VAULT_PASSWORD_FILE ~/.ansible_vault_pass
set -gx EDITOR nano

# For bash/zsh, use:
# export ANSIBLE_VAULT_PASSWORD_FILE=~/.ansible_vault_pass
# export EDITOR=nano

# Install Ansible (inside your virtualenv)
pip install ansible
```

**Step 6: Encrypt Vault File**
```bash
ansible-vault encrypt config/ansible/vault/production-vault.yml
```

**Step 7: Build Container Image**
```bash
make build TAG=v0.1.2
# Replace v0.1.2 with your desired version tag
```

**Step 8: Update Inventory with Image Tag**
```bash
# Edit config/ansible/inventory/hosts.yml
# Update image_tag to match the tag you used in Step 7:
#   image_tag: v0.1.2
```

**Step 9: Deploy to Production**
```bash
make deploy-production
```

**Note:** The `config/` directory is gitignored to protect your private deployment information. Default templates in `deployment/ansible/templates/` work out-of-the-box. Only copy templates to `config/ansible/templates/` if you need deployment-specific customizations.

### 2. Build Container Image

```bash
make build TAG=v1.0.0
```

This builds the container and pushes to your registry (from `.senextrader.json`).

### 3. Deploy to Production

```bash
make deploy-production
```

This uses Ansible to:
- Pull latest container image
- Update environment variables
- Restart services
- Run database migrations

---

## 📁 Repository Structure

```
senextrader/                         # Monorepo root
├── .senextrader.json                # Build config (gitignored, use .example)
├── build.py                          # Container build script
├── Makefile                          # Deployment commands
├── deployment/
│   ├── ansible/
│   │   ├── ansible.cfg              # Ansible configuration
│   │   ├── deploy.yml               # Main deployment playbook
│   │   ├── inventory/
│   │   │   ├── hosts.yml            # Your servers (gitignored, use .example)
│   │   │   ├── hosts.yml.example    # Template for hosts.yml
│   │   │   ├── *-vault.yml          # Encrypted secrets (gitignored)
│   │   │   └── *-vault.yml.example  # Template for vaults
│   │   ├── playbooks/               # Ansible playbooks
│   │   └── roles/                   # Ansible roles
│   └── docker/
│       └── Dockerfile               # Container image definition
```

---

## Configuration Files

### `.senextrader.json` (Build Configuration)

**Location:** Project root
**Gitignored:** Yes (use `.senextrader.json.example` as template)

```json
{
  "registry": "your-registry.example.com",
  "owner": "username",
  "image_name": "senex-trader",
  "project_dir": null,
  "default_no_push": false
}
```

### `config/ansible/inventory/hosts.yml` (Server Inventory)

**Your config:** `config/ansible/inventory/hosts.yml` (gitignored)
**Template:** `deployment/ansible/inventory/hosts.yml.example`

```yaml
production:
  hosts:
    senextrader-production:
      ansible_host: your-server.example.com
      ansible_user: root
      # ... server-specific vars
```

### Vault Files (Encrypted Secrets)

**Your vaults:** `config/ansible/vault/` (gitignored)
**Templates:** `deployment/ansible/inventory/*-vault.yml.example`

**Important:** All sensitive data (passwords, secrets, API keys) goes in vault files, NOT in templates. Templates use variables that are populated from vault files during deployment.

Create encrypted vaults:
```bash
# Copy example template
cp deployment/ansible/inventory/production-vault.yml.example config/ansible/vault/production-vault.yml

# Edit with your values
ansible-vault edit config/ansible/vault/production-vault.yml

# Or create new vault
ansible-vault create config/ansible/vault/production-vault.yml
```

### Quadlet Container Templates

**Default templates:** `deployment/ansible/templates/quadlet/*.j2` (tracked in git, generic)
**Custom overrides:** `config/ansible/templates/quadlet/*.j2` (gitignored, deployment-specific)

The deployment playbook automatically uses templates from `config/` if they exist, otherwise falls back to defaults in `deployment/`. This means:
- Default templates work out-of-the-box (no copying required)
- You can customize by copying templates to `config/ansible/templates/quadlet/` and modifying them
- All templates use variables (`{{ app_directory }}`, `{{ quadlet_dir }}`) - no hardcoded paths
- No sensitive data in templates - all secrets come from vault files

---

## Build Process

### Using Makefile (Recommended)

```bash
# Build and push to registry
make build TAG=v1.0.0

# Build without pushing (testing)
./build.py --tag test-build --no-push
```

### Manual Build

```bash
# Direct podman build
podman build -t senex-trader:v1.0.0 -f deployment/docker/Dockerfile .

# Push to registry
podman tag senex-trader:v1.0.0 your-registry.example.com/your-org/senex-trader:v1.0.0
podman push your-registry.example.com/your-org/senex-trader:v1.0.0
```

---

## 🚢 Deployment Process

### Full Deployment (Recommended)

```bash
make deploy-production
```

**What this does:**
1. Validates configuration
2. Pulls latest container image
3. Configures environment variables (from vault)
4. Updates Quadlet service definitions
5. Restarts services
6. Runs database migrations
7. Collects static files

### Staging Deployment

```bash
make deploy-staging
```

### Manual Deployment

For quick updates (single file changes):

```bash
# Copy file to production
scp services/position_sync.py root@your-server.example.com:/tmp/

# Update file in container
ssh root@your-server.example.com "su - senex -c 'podman cp /tmp/position_sync.py web:/app/services/'"

# Restart if needed
ssh root@your-server.example.com "su - senex -c 'systemctl --user restart web.service'"
```

---

## Secrets Management

### Setup Vault Password

```bash
# Create vault password file (use a secure password)
nano ~/.ansible_vault_pass
# Enter your vault password, save and exit

# Secure the password file
chmod 600 ~/.ansible_vault_pass

# Set environment variable (fish shell)
set -gx ANSIBLE_VAULT_PASSWORD_FILE ~/.ansible_vault_pass
set -gx EDITOR nano

# For bash/zsh:
# export ANSIBLE_VAULT_PASSWORD_FILE=~/.ansible_vault_pass
# export EDITOR=nano
```

### Install Ansible

```bash
# Install Ansible in your virtualenv
pip install ansible
```

### Create/Edit Vaults

```bash
# Copy example template first
cp deployment/ansible/inventory/production-vault.yml.example config/ansible/vault/production-vault.yml

# Edit with your values (unencrypted)
nano config/ansible/vault/production-vault.yml

# Encrypt the vault file
ansible-vault encrypt config/ansible/vault/production-vault.yml

# Edit existing encrypted vault
ansible-vault edit config/ansible/vault/production-vault.yml

# View vault contents (read-only)
ansible-vault view config/ansible/vault/production-vault.yml
```

### Generate Secure Secrets

```bash
# Django SECRET_KEY
python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# FIELD_ENCRYPTION_KEY (Fernet)
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

# Database password (strong random)
openssl rand -base64 24
```

### Vault Structure

```yaml
---
# Production secrets (encrypted with ansible-vault)
django_secret_key: "your-secret-key-here"
db_password: "your-db-password"
tastytrade_username: "your-username"
tastytrade_password: "your-password"
redis_password: "your-redis-password"
```

---

## Common Tasks

### View Current Configuration

```bash
make check-config
```

### Deploy Latest Code Changes

```bash
# 1. Build new image
make build TAG=v1.0.1

# 2. Deploy
make deploy-production
```

### Update Single File (Quick Fix)

```bash
# For Python files that don't need rebuild
scp path/to/file.py root@your-server.example.com:/tmp/
ssh root@your-server.example.com "su - senex -c 'podman cp /tmp/file.py web:/app/path/to/'"
```

### Rollback Deployment

```bash
# Edit hosts.yml to use previous image tag
vim config/ansible/inventory/hosts.yml
# Change: image_tag: v1.0.0  (previous version)

# Redeploy
make deploy-production
```

### View Service Logs

```bash
ssh root@your-server.example.com "su - senex -c 'podman logs --tail 100 web'"
ssh root@your-server.example.com "su - senex -c 'podman logs --tail 100 celery-worker'"
```

---

## Troubleshooting

### Configuration Not Found

**Error:** `SENEX_CONFIG_PATH not set`

**Solution:** Not needed anymore! Update to latest Makefile (uses local files).

### Ansible Can't Find Inventory

**Check:**
```bash
ls -la config/ansible/inventory/hosts.yml
```

**Fix:**
```bash
cp deployment/ansible/inventory/hosts.yml.example config/ansible/inventory/hosts.yml
# Edit with your server details
```

### Build Script Can't Find Config

**Check:**
```bash
ls -la .senextrader.json
```

**Fix:**
```bash
cp .senextrader.json.example .senextrader.json
# Edit with your registry details
```

### Vault Decryption Fails

**Check:**
```bash
cat ~/.ansible_vault_pass
```

**Fix:**
```bash
echo "your-vault-password" > ~/.ansible_vault_pass
chmod 600 ~/.ansible_vault_pass
```

---

## 📚 Additional Documentation

- **Application Setup:** `README.md` (project root)
- **Development Guide:** `docs/DEVELOPMENT.md`
- **Environment Variables:** `.env.example`, `.env.production.example`

---

## Makefile Commands

```bash
make help              # Show all commands
make setup             # Validate configuration
make check-config      # Display current config
make build TAG=vX.X.X  # Build container image
make deploy-staging    # Deploy to staging
make deploy-production # Deploy to production
```

---

## Security Notes

**Gitignored Files (Never Commit):**
- `config/` directory - All your private deployment configs
- `.senextrader.json` - Your container registry
- `config/ansible/inventory/hosts.yml` - Your server IPs
- `config/ansible/vault/*-vault.yml` - Encrypted secrets
- `.vault_pass*` - Vault password files

**Safe to Commit:**
- All `.example` files
- All code files
- Ansible playbooks and roles
- Dockerfile
- Default templates in `deployment/ansible/templates/` (generic, use variables)

**Security Guarantees:**
- **No sensitive data in tracked files:** All passwords/secrets come from Ansible Vault via `env.j2`
- **No hardcoded paths:** All templates use variables (`{{ app_directory }}`, `{{ quadlet_dir }}`)
- **No infrastructure details:** No domain names, IPs, or server-specific configs in tracked templates
- **Generic defaults:** Templates work for any deployment without modification
- **Customization path:** Deployment-specific changes go in gitignored `config/` directory

---

**Last Updated:** 2025-11-03
**Deployment Model:** Monorepo (all-in-one)
