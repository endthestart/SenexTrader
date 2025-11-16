# Environment Variables Reference

## Overview

This document provides a comprehensive reference for all environment variables required and supported by Senex Trader containers. Variables are organized by category with generation commands, defaults, and security considerations.

---

## Quick Reference

### Required Variables (Production)

These variables **MUST** be set for production deployment:

```bash
SECRET_KEY                 # Django secret key (generate: see below)
FIELD_ENCRYPTION_KEY       # Fernet encryption key (generate: see below)
DB_PASSWORD                # PostgreSQL password
TASTYTRADE_CLIENT_ID       # TastyTrade OAuth client ID
TASTYTRADE_CLIENT_SECRET   # TastyTrade OAuth client secret
```

### Recommended Variables (Production)

These variables should be set for production:

```bash
ALLOWED_HOSTS              # Comma-separated list of allowed hosts
WS_ALLOWED_ORIGINS         # Comma-separated list of WebSocket origins
APP_BASE_URL               # Base URL for application (e.g., https://your-domain.com)
DB_NAME                    # PostgreSQL database name (default: senex_trader)
DB_USER                    # PostgreSQL username (default: senex_user)
DB_HOST                    # PostgreSQL hostname (default: postgres)
REDIS_URL                  # Redis connection URL (default: redis://redis:6379/0)
```

### Optional Variables

These variables have sensible defaults:

```bash
ENVIRONMENT                # Environment name (production, development)
DJANGO_SETTINGS_MODULE     # Settings module to use
EMAIL_HOST                 # SMTP host for email
EMAIL_PORT                 # SMTP port (default: 587)
SENTRY_DSN                 # Sentry error tracking DSN
```

---

## Category: Django Core

### SECRET_KEY

**Purpose**: Django's secret key for cryptographic signing

**Required**: Yes (production)

**Security**: CRITICAL - Never commit to version control

**Generation Command**:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**Example Output**:
```
django-insecure-7j#k2$m9n@p3q!r5s*t8u&v1w^x4y+z6a=b0c_d2e-f3g5h7
```

**Length**: 50-100 characters

**Default**: None (must be explicitly set)

**Docker Compose Example**:
```yaml
environment:
  SECRET_KEY: ${SECRET_KEY}
```

---

### FIELD_ENCRYPTION_KEY

**Purpose**: Fernet symmetric encryption key for sensitive database fields (OAuth tokens, API keys)

**Required**: Yes (production)

**Security**: CRITICAL - Never commit to version control

**Generation Command**:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Example Output**:
```
vQ7tG9xK2pL8mN4rS6uT0wY3zB5cD7eF1hJ9kM0nP2qR4sT6u=
```

**Format**: Base64-encoded 32-byte key (44 characters with trailing =)

**Default**: None (must be explicitly set)

**Docker Compose Example**:
```yaml
environment:
  FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}
```

**Used By**: `django-encrypted-model-fields` for TradingAccount OAuth tokens

---

### DJANGO_SETTINGS_MODULE

**Purpose**: Django settings module to load

**Required**: No (auto-detected)

**Default**: Determined by `ENVIRONMENT` variable
- If `ENVIRONMENT=production`: `senex_trader.settings.production`
- Otherwise: `senex_trader.settings.development`

**Options**:
- `senex_trader.settings.development` - Development settings (SQLite, DEBUG=True)
- `senex_trader.settings.production` - Production settings (PostgreSQL, DEBUG=False)

**Docker Compose Example**:
```yaml
environment:
  DJANGO_SETTINGS_MODULE: senex_trader.settings.production
```

**Note**: Usually better to set `ENVIRONMENT` variable instead (simpler)

---

### ENVIRONMENT

**Purpose**: Environment name for automatic settings module selection

**Required**: No

**Default**: `development`

**Options**:
- `production` - Production environment
- `development` - Development environment
- `staging` - Staging environment (uses production settings)

**Docker Compose Example**:
```yaml
environment:
  ENVIRONMENT: production
```

**Effect**: Automatically sets `DJANGO_SETTINGS_MODULE` to appropriate module

---

### ALLOWED_HOSTS

**Purpose**: Django's ALLOWED_HOSTS setting (security protection against HTTP Host header attacks)

**Required**: Yes (production)

**Format**: Comma-separated list of hostnames

**Example**:
```bash
ALLOWED_HOSTS=your-domain.com,api.your-domain.com,www.your-domain.com
```

**Default (Development)**: `localhost,127.0.0.1`

**Default (Production)**: Empty (must be explicitly set)

**Docker Compose Example**:
```yaml
environment:
  ALLOWED_HOSTS: your-domain.com,api.your-domain.com
```

**Security**: Django will reject requests with Host header not in this list

---

### WS_ALLOWED_ORIGINS

**Purpose**: Allowed origins for WebSocket connections (CORS for WebSockets)

**Required**: Yes (production)

**Format**: Comma-separated list of origins (with protocol)

**Example**:
```bash
WS_ALLOWED_ORIGINS=https://your-domain.com,https://api.your-domain.com
```

**Default (Development)**: `http://localhost:8000,http://127.0.0.1:8000`

**Default (Production)**: Empty (must be explicitly set)

**Docker Compose Example**:
```yaml
environment:
  WS_ALLOWED_ORIGINS: https://your-domain.com,https://api.your-domain.com
```

**Note**: Must include protocol (http:// or https://)

---

### APP_BASE_URL

**Purpose**: Base URL for application (used for generating absolute URLs)

**Required**: No (recommended for production)

**Format**: Full URL with protocol

**Example**:
```bash
APP_BASE_URL=https://your-domain.com
```

**Default**: `http://localhost:8000`

**Docker Compose Example**:
```yaml
environment:
  APP_BASE_URL: https://your-domain.com
```

**Used By**: Email templates, API responses with URLs, OAuth callbacks

---

## Category: Database (PostgreSQL)

### DB_NAME

**Purpose**: PostgreSQL database name

**Required**: No

**Default**: `senex_trader`

**Docker Compose Example**:
```yaml
environment:
  DB_NAME: senex_trader
```

**Note**: Must match PostgreSQL container's `POSTGRES_DB`

---

### DB_USER

**Purpose**: PostgreSQL username

**Required**: No

**Default**: `senex_user`

**Docker Compose Example**:
```yaml
environment:
  DB_USER: senex_user
```

**Note**: Must match PostgreSQL container's `POSTGRES_USER`

---

### DB_PASSWORD

**Purpose**: PostgreSQL password

**Required**: Yes (production)

**Security**: CRITICAL - Never commit to version control

**Generation Command**:
```bash
openssl rand -base64 32
```

**Example Output**:
```
xJ3kR7mN2pQ5sT8uW1vY4zA6bC9dE0fG2hJ5kM8nP1qR=
```

**Default**: None (must be explicitly set)

**Docker Compose Example**:
```yaml
environment:
  DB_PASSWORD: ${DB_PASSWORD}
```

**Note**: Must match PostgreSQL container's `POSTGRES_PASSWORD`

---

### DB_HOST

**Purpose**: PostgreSQL hostname

**Required**: No

**Default**: `postgres` (Docker Compose service name)

**Docker Compose Example**:
```yaml
environment:
  DB_HOST: postgres
```

**Production**: Use cloud database hostname (e.g., RDS endpoint)

---

### DB_PORT

**Purpose**: PostgreSQL port

**Required**: No

**Default**: `5432`

**Docker Compose Example**:
```yaml
environment:
  DB_PORT: 5432
```

---

### DB_SSL_MODE

**Purpose**: PostgreSQL SSL mode (for cloud databases)

**Required**: No

**Default**: `require` (production), `prefer` (development)

**Options**:
- `disable` - No SSL
- `prefer` - SSL if available
- `require` - SSL required (reject if unavailable)
- `verify-ca` - SSL required, verify CA
- `verify-full` - SSL required, verify CA and hostname

**Docker Compose Example**:
```yaml
environment:
  DB_SSL_MODE: require
```

---

## Category: Redis

### REDIS_URL

**Purpose**: Redis connection URL (cache, session storage, channels backend)

**Required**: No

**Default**: `redis://redis:6379/0`

**Format**: `redis://[password@]host:port/database`

**Example**:
```bash
REDIS_URL=redis://redis:6379/0
```

**With Password**:
```bash
REDIS_URL=redis://:mypassword@redis:6379/0
```

**Docker Compose Example**:
```yaml
environment:
  REDIS_URL: redis://redis:6379/0
```

**Note**: Uses Redis DB 0 for cache and channels

---

### CELERY_BROKER_URL

**Purpose**: Celery message broker URL

**Required**: No

**Default**: `redis://redis:6379/2`

**Format**: `redis://[password@]host:port/database`

**Docker Compose Example**:
```yaml
environment:
  CELERY_BROKER_URL: redis://redis:6379/2
```

**Note**: Uses Redis DB 2 for Celery broker

---

### CELERY_RESULT_BACKEND

**Purpose**: Celery result storage backend

**Required**: No

**Default**: `redis://redis:6379/3`

**Format**: `redis://[password@]host:port/database`

**Docker Compose Example**:
```yaml
environment:
  CELERY_RESULT_BACKEND: redis://redis:6379/3
```

**Note**: Uses Redis DB 3 for Celery results

---

## Category: TastyTrade API

### TASTYTRADE_CLIENT_ID

**Purpose**: TastyTrade OAuth 2.0 client ID

**Required**: Yes (for trading functionality)

**Obtain From**: TastyTrade developer portal

**Format**: String (length varies)

**Example**: `abc123def456`

**Docker Compose Example**:
```yaml
environment:
  TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID}
```

**Security**: Not highly sensitive, but don't publish publicly

---

### TASTYTRADE_CLIENT_SECRET

**Purpose**: TastyTrade OAuth 2.0 client secret

**Required**: Yes (for trading functionality)

**Security**: CRITICAL - Never commit to version control

**Obtain From**: TastyTrade developer portal

**Format**: String (length varies)

**Docker Compose Example**:
```yaml
environment:
  TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET}
```

---

### TASTYTRADE_BASE_URL

**Purpose**: TastyTrade API base URL

**Required**: No (auto-detected by TastyTrade SDK)

**Default**: SDK chooses production automatically

**Options**:
- `https://api.tastyworks.com` - Production
- `https://api.cert.tastyworks.com` - Sandbox

**Docker Compose Example**:
```yaml
environment:
  TASTYTRADE_BASE_URL: https://api.tastyworks.com
```

**Note**: TastyTrade SDK v10+ auto-manages URLs, so this is usually not needed

---

## Category: Security & SSL

### SECURE_SSL_REDIRECT

**Purpose**: Force redirect from HTTP to HTTPS

**Required**: No

**Default**: `True` (production), `False` (development)

**Options**: `True`, `False`

**Docker Compose Example**:
```yaml
environment:
  SECURE_SSL_REDIRECT: True
```

**Note**: Only enable if reverse proxy handles SSL termination

---

### SECURE_HSTS_SECONDS

**Purpose**: HTTP Strict Transport Security (HSTS) max-age

**Required**: No

**Default**: `31536000` (1 year in production)

**Format**: Seconds

**Docker Compose Example**:
```yaml
environment:
  SECURE_HSTS_SECONDS: 31536000
```

**Security**: Browsers will only access site via HTTPS for specified duration

---

### SECURE_HSTS_INCLUDE_SUBDOMAINS

**Purpose**: Include subdomains in HSTS policy

**Required**: No

**Default**: `True` (production)

**Options**: `True`, `False`

**Docker Compose Example**:
```yaml
environment:
  SECURE_HSTS_INCLUDE_SUBDOMAINS: True
```

---

### SECURE_HSTS_PRELOAD

**Purpose**: Allow HSTS preload list submission

**Required**: No

**Default**: `True` (production)

**Options**: `True`, `False`

**Docker Compose Example**:
```yaml
environment:
  SECURE_HSTS_PRELOAD: True
```

**Note**: Submit to https://hstspreload.org/ for browser preload list

---

## Category: Email (Optional)

### EMAIL_HOST

**Purpose**: SMTP server hostname

**Required**: No (only if email notifications desired)

**Example**: `smtp.gmail.com`, `smtp.sendgrid.net`

**Docker Compose Example**:
```yaml
environment:
  EMAIL_HOST: smtp.gmail.com
```

---

### EMAIL_PORT

**Purpose**: SMTP server port

**Required**: No

**Default**: `587`

**Options**:
- `587` - STARTTLS
- `465` - SSL/TLS
- `25` - Unencrypted (not recommended)

**Docker Compose Example**:
```yaml
environment:
  EMAIL_PORT: 587
```

---

### EMAIL_USE_TLS

**Purpose**: Use STARTTLS for SMTP

**Required**: No

**Default**: `True`

**Options**: `True`, `False`

**Docker Compose Example**:
```yaml
environment:
  EMAIL_USE_TLS: True
```

---

### EMAIL_HOST_USER

**Purpose**: SMTP username

**Required**: No (only if SMTP requires authentication)

**Example**: `[email protected]`

**Docker Compose Example**:
```yaml
environment:
  EMAIL_HOST_USER: ${EMAIL_HOST_USER}
```

---

### EMAIL_HOST_PASSWORD

**Purpose**: SMTP password

**Required**: No (only if SMTP requires authentication)

**Security**: CRITICAL - Never commit to version control

**Docker Compose Example**:
```yaml
environment:
  EMAIL_HOST_PASSWORD: ${EMAIL_HOST_PASSWORD}
```

---

### DEFAULT_FROM_EMAIL

**Purpose**: Default "From" address for emails

**Required**: No

**Default**: `[email protected]`

**Example**: `[email protected]`

**Docker Compose Example**:
```yaml
environment:
  DEFAULT_FROM_EMAIL: [email protected]
```

---

## Category: Monitoring (Optional)

### SENTRY_DSN

**Purpose**: Sentry error tracking DSN

**Required**: No (optional)

**Format**: `https://<key>@<organization>.ingest.sentry.io/<project>`

**Docker Compose Example**:
```yaml
environment:
  SENTRY_DSN: ${SENTRY_DSN}
```

**Obtain From**: Sentry project settings

---

## Category: Advanced (Rarely Changed)

### PUID / PGID

**Purpose**: Runtime UID/GID modification for volume permission matching

**Required**: No

**Default**: Use container's built-in UID/GID (1000)

**Example**:
```bash
PUID=1001
PGID=1001
```

**Docker Compose Example**:
```yaml
environment:
  PUID: 1001
  PGID: 1001
```

**Note**: Only needed if host volume permissions don't match container UID/GID 1000

---

### CELERY_TASK_ALWAYS_EAGER

**Purpose**: Execute Celery tasks synchronously (for testing)

**Required**: No

**Default**: `False`

**Options**: `True`, `False`

**Docker Compose Example**:
```yaml
environment:
  CELERY_TASK_ALWAYS_EAGER: True
```

**Use Case**: Unit testing (tasks execute immediately without broker)

---

## Environment File Templates

### .env (Development)

```bash
# ============================================================================
# Development Environment Variables
# ============================================================================

# Django Core
ENVIRONMENT=development
SECRET_KEY=django-insecure-dev-key-CHANGE-THIS
FIELD_ENCRYPTION_KEY=dev-key-CHANGE-THIS
ALLOWED_HOSTS=localhost,127.0.0.1
WS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
APP_BASE_URL=http://localhost:8000

# Database (SQLite for development)
# No DB_* variables needed (uses SQLite)

# Redis (local)
REDIS_URL=redis://127.0.0.1:6379/1
CELERY_BROKER_URL=redis://127.0.0.1:6379/2
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/3

# TastyTrade API (use sandbox)
TASTYTRADE_CLIENT_ID=your-dev-client-id
TASTYTRADE_CLIENT_SECRET=your-dev-client-secret
TASTYTRADE_BASE_URL=https://api.cert.tastyworks.com

# Security (disabled for dev)
SECURE_SSL_REDIRECT=False

# Email (console backend for dev)
# No email variables needed (prints to console)
```

---

### .env.production (Production)

```bash
# ============================================================================
# Production Environment Variables
# ============================================================================
# SECURITY: Never commit this file to version control
# ============================================================================

# Django Core
ENVIRONMENT=production
SECRET_KEY=<GENERATE_WITH_COMMAND_ABOVE>
FIELD_ENCRYPTION_KEY=<GENERATE_WITH_COMMAND_ABOVE>
ALLOWED_HOSTS=your-domain.com,api.your-domain.com
WS_ALLOWED_ORIGINS=https://your-domain.com,https://api.your-domain.com
APP_BASE_URL=https://your-domain.com

# Database (PostgreSQL)
DB_NAME=senex_trader
DB_USER=senex_user
DB_PASSWORD=<GENERATE_WITH_OPENSSL>
DB_HOST=postgres
DB_PORT=5432

# Redis
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/2
CELERY_RESULT_BACKEND=redis://redis:6379/3

# TastyTrade API (production)
TASTYTRADE_CLIENT_ID=<FROM_TASTYTRADE_PORTAL>
TASTYTRADE_CLIENT_SECRET=<FROM_TASTYTRADE_PORTAL>
TASTYTRADE_BASE_URL=https://api.tastyworks.com

# Security
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

# Email (optional)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<YOUR_EMAIL>
EMAIL_HOST_PASSWORD=<YOUR_APP_PASSWORD>
DEFAULT_FROM_EMAIL=[email protected]

# Monitoring (optional)
SENTRY_DSN=<FROM_SENTRY_PROJECT>
```

---

### docker-compose.yml Environment Variable Usage

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${DB_NAME:-senex_trader}
      POSTGRES_USER: ${DB_USER:-senex_user}
      POSTGRES_PASSWORD: ${DB_PASSWORD}

  redis:
    image: redis:7-alpine

  web:
    build: .
    environment:
      # Django Core
      ENVIRONMENT: ${ENVIRONMENT:-production}
      SECRET_KEY: ${SECRET_KEY}
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}
      ALLOWED_HOSTS: ${ALLOWED_HOSTS}
      WS_ALLOWED_ORIGINS: ${WS_ALLOWED_ORIGINS}
      APP_BASE_URL: ${APP_BASE_URL}

      # Database
      DB_NAME: ${DB_NAME:-senex_trader}
      DB_USER: ${DB_USER:-senex_user}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_HOST: postgres
      DB_PORT: 5432

      # Redis
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/2
      CELERY_RESULT_BACKEND: redis://redis:6379/3

      # TastyTrade
      TASTYTRADE_CLIENT_ID: ${TASTYTRADE_CLIENT_ID}
      TASTYTRADE_CLIENT_SECRET: ${TASTYTRADE_CLIENT_SECRET}
      TASTYTRADE_BASE_URL: ${TASTYTRADE_BASE_URL:-https://api.tastyworks.com}

      # Security
      SECURE_SSL_REDIRECT: ${SECURE_SSL_REDIRECT:-True}
      SECURE_HSTS_SECONDS: ${SECURE_HSTS_SECONDS:-31536000}

      # Email (optional)
      EMAIL_HOST: ${EMAIL_HOST:-}
      EMAIL_PORT: ${EMAIL_PORT:-587}
      EMAIL_USE_TLS: ${EMAIL_USE_TLS:-True}
      EMAIL_HOST_USER: ${EMAIL_HOST_USER:-}
      EMAIL_HOST_PASSWORD: ${EMAIL_HOST_PASSWORD:-}
      DEFAULT_FROM_EMAIL: ${DEFAULT_FROM_EMAIL:-[email protected]}

      # Monitoring (optional)
      SENTRY_DSN: ${SENTRY_DSN:-}

  # celery_worker and celery_beat use same environment variables
```

---

## Secret Management Best Practices

### 1. Never Commit Secrets

**Gitignore**:
```
.env
.env.production
.env.local
*.pem
*.key
```

### 2. Use Secret Management Service

**Options**:
- **Docker Secrets** (Swarm mode)
- **Kubernetes Secrets**
- **AWS Secrets Manager**
- **HashiCorp Vault**
- **Azure Key Vault**
- **GCP Secret Manager**

### 3. Generate Strong Secrets

**Minimum Requirements**:
- `SECRET_KEY`: 50+ characters, alphanumeric + special
- `FIELD_ENCRYPTION_KEY`: 44 characters (base64-encoded 32 bytes)
- `DB_PASSWORD`: 32+ characters, alphanumeric

### 4. Rotate Secrets Regularly

**Recommended Schedule**:
- `SECRET_KEY`: Annually
- `FIELD_ENCRYPTION_KEY`: Never (will break existing encrypted data)
- `DB_PASSWORD`: Quarterly
- `TASTYTRADE_CLIENT_SECRET`: When compromised

### 5. Separate Environments

**Pattern**: Use different secrets for dev/staging/production

**Example**:
- Dev: `.env` (weak secrets okay)
- Staging: `.env.staging` (production-strength secrets)
- Production: `.env.production` (stored in secret manager, not on disk)

---

## Validation Checklist

Before deploying, verify all required variables are set:

```bash
#!/bin/bash
# validate-env.sh

required_vars=(
    "SECRET_KEY"
    "FIELD_ENCRYPTION_KEY"
    "DB_PASSWORD"
    "TASTYTRADE_CLIENT_ID"
    "TASTYTRADE_CLIENT_SECRET"
)

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "ERROR: Required variable $var is not set"
        exit 1
    fi
done

echo "All required environment variables are set"
```

**Usage**:
```bash
source .env.production
./validate-env.sh
```

---

## Summary

Senex Trader requires:

- ✅ **5 Required Variables**: SECRET_KEY, FIELD_ENCRYPTION_KEY, DB_PASSWORD, TASTYTRADE_CLIENT_ID, TASTYTRADE_CLIENT_SECRET
- ✅ **10+ Recommended Variables**: Database, Redis, security, CORS settings
- ✅ **15+ Optional Variables**: Email, monitoring, advanced tuning
- ✅ **Secret Generation Commands**: Provided for all sensitive variables
- ✅ **Environment Templates**: Development and production ready-to-use
- ✅ **Security Guidance**: Never commit secrets, use secret managers

**Next Steps**:
- Generate all required secrets
- Create `.env.production` from template
- Store secrets in secret manager
- See `docker-compose-strategy.md` for orchestration
