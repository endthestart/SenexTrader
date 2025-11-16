# Ansible Structure and Organization

## Overview

This deployment uses Ansible with the `containers.podman` collection to manage rootless Podman containers via systemd Quadlet. The structure follows Ansible best practices with role-based organization and environment-specific variables.

## Directory Structure

```
ansible-deployment/
├── ansible.cfg                         # Ansible configuration
├── requirements.yml                    # Required Ansible collections
├── site.yml                           # Main orchestration playbook
├── inventory/
│   ├── production/
│   │   ├── hosts.yml                  # Production server inventory
│   │   └── group_vars/
│   │       ├── all.yml                # Shared production variables
│   │       ├── vault.yml              # Encrypted secrets (Ansible Vault)
│   │       └── webservers.yml         # Web server specific vars
│   └── staging/
│       ├── hosts.yml                  # Staging server inventory
│       └── group_vars/
│           ├── all.yml                # Shared staging variables
│           └── vault.yml              # Encrypted staging secrets
├── playbooks/
│   ├── deploy.yml                     # Main deployment playbook
│   ├── backup.yml                     # Backup execution playbook
│   ├── rollback.yml                   # Rollback playbook
│   └── health-check.yml               # Health validation playbook
├── roles/
│   ├── common/                        # System prep, users, firewall
│   │   ├── tasks/
│   │   ├── handlers/
│   │   ├── templates/
│   │   └── defaults/
│   ├── podman/                        # Podman installation & config
│   ├── postgresql/                    # PostgreSQL container
│   ├── redis/                         # Redis container
│   ├── django/                        # Django/Daphne containers
│   ├── celery/                        # Celery worker & beat
│   ├── nginx/                         # Nginx reverse proxy
│   ├── letsencrypt/                   # SSL certificate automation
│   ├── monitoring/                    # Prometheus/Grafana
│   └── backup/                        # Backup automation
└── files/
    ├── quadlet/                       # Systemd Quadlet templates
    ├── nginx/                         # Nginx configuration files
    └── scripts/                       # Helper scripts
```

## Required Ansible Collections

**requirements.yml**:
```yaml
collections:
  - name: containers.podman
    version: ">=1.17.0"
  - name: community.crypto
    version: ">=2.0.0"
  - name: ansible.posix
    version: ">=1.5.0"
  - name: community.general
    version: ">=8.0.0"
```

**Install collections**:
```bash
ansible-galaxy collection install -r requirements.yml
```

## Ansible Configuration

**ansible.cfg**:
```ini
[defaults]
inventory = inventory/production/hosts.yml
roles_path = ./roles
collections_path = ~/.ansible/collections
host_key_checking = False
retry_files_enabled = False
gathering = smart
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts
fact_caching_timeout = 3600

# Use multiple Vault IDs for different environments
vault_identity_list = staging@~/.vault_pass_staging, production@~/.vault_pass_production

# Output
stdout_callback = yaml
callbacks_enabled = timer, profile_tasks

# SSH
remote_user = senex
private_key_file = ~/.ssh/id_ed25519
timeout = 30

[privilege_escalation]
become = False  # Use rootless Podman
become_method = sudo
become_user = root
become_ask_pass = False

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s
pipelining = True
```

## Inventory Structure

### Production Inventory

**inventory/production/hosts.yml**:
```yaml
all:
  children:
    webservers:
      hosts:
        web01.your-domain.com:
          ansible_host: 10.0.1.10
          ansible_user: senex

    database:
      hosts:
        db01.your-domain.com:
          ansible_host: 10.0.1.20
          ansible_user: senex

    cache:
      hosts:
        redis01.your-domain.com:
          ansible_host: 10.0.1.30
          ansible_user: senex

  vars:
    ansible_python_interpreter: /usr/bin/python3
    environment_name: production
```

**inventory/production/group_vars/all.yml**:
```yaml
# Application configuration
app_name: senextrader
app_user: senex
app_dir: /opt/senex-trader
config_dir: /etc/senex-trader
log_dir: /var/log/senex-trader

# Domain configuration
domain_name: your-domain.com
allowed_hosts: "your-domain.com,www.your-domain.com"

# Django settings
django_settings_module: senextrader.settings.production
django_image: "registry.example.com/senex-trader"
django_version: "{{ lookup('env', 'IMAGE_TAG') | default('latest', true) }}"

# Service settings
enable_ssl: true
enable_monitoring: true
backup_enabled: true

# Podman network
podman_network_name: senex_net
podman_network_subnet: "172.20.0.0/16"
```

**inventory/production/group_vars/vault.yml** (encrypted):
```yaml
# Run: ansible-vault create inventory/production/group_vars/vault.yml
vault_secret_key: "django-insecure-CHANGE-THIS-IN-PRODUCTION"
vault_field_encryption_key: "FERNET-KEY-GENERATED-WITH-CRYPTOGRAPHY"

vault_db_name: senextrader
vault_db_user: senex_user
vault_db_password: "STRONG-DB-PASSWORD"

vault_redis_password: "STRONG-REDIS-PASSWORD"

vault_tastytrade_client_id: "YOUR-TASTYTRADE-CLIENT-ID"
vault_tastytrade_client_secret: "YOUR-TASTYTRADE-CLIENT-SECRET"

vault_email_host_password: "EMAIL-PASSWORD"

# Optional: Sentry DSN
vault_sentry_dsn: "https://...@sentry.io/..."
```

## Role Descriptions

### 1. common (System Preparation)

**Purpose**: Prepare server with required packages, users, and security

**Tasks**:
- Install system packages (Podman, Python, tools)
- Create application user
- Configure firewall (ufw/firewalld)
- Set up fail2ban
- Enable unattended upgrades
- Configure systemd lingering for rootless containers

**Example Task** (roles/common/tasks/main.yml):
```yaml
- name: Install required packages
  ansible.builtin.package:
    name:
      - podman
      - python3
      - python3-pip
      - git
      - curl
      - ufw
      - fail2ban
    state: present
  become: true

- name: Create application user
  ansible.builtin.user:
    name: "{{ app_user }}"
    shell: /bin/bash
    create_home: yes
    groups: wheel
  become: true

- name: Enable systemd lingering
  ansible.builtin.command:
    cmd: "loginctl enable-linger {{ app_user }}"
    creates: "/var/lib/systemd/linger/{{ app_user }}"
  become: true
```

### 2. podman (Container Runtime)

**Purpose**: Install and configure Podman for rootless operation

**Tasks**:
- Install Podman from official repos
- Configure subuid/subgid for user namespaces
- Create Podman network
- Set up volume directories
- Configure systemd directories for Quadlet

**Example Task** (roles/podman/tasks/main.yml):
```yaml
- name: Configure subuid for rootless containers
  ansible.builtin.lineinfile:
    path: /etc/subuid
    line: "{{ app_user }}:100000:65536"
    create: yes
  become: true

- name: Create Podman network
  containers.podman.podman_network:
    name: "{{ podman_network_name }}"
    subnet: "{{ podman_network_subnet }}"
    state: present
  become: false

- name: Create systemd user directory
  ansible.builtin.file:
    path: "~{{ app_user }}/.config/containers/systemd"
    state: directory
    owner: "{{ app_user }}"
    mode: '0755'
```

### 3. postgresql (Database Container)

**Purpose**: Deploy PostgreSQL container with persistence

**Tasks**:
- Create PostgreSQL data volume
- Deploy Quadlet file for PostgreSQL container
- Configure SSL connections
- Set up health checks
- Create database and user

**Quadlet Template** (roles/postgresql/templates/postgresql.container.j2):
```ini
[Unit]
Description=PostgreSQL Database
After=network-online.target

[Container]
Image=docker.io/library/postgres:16
ContainerName=postgres
Volume=postgres_data:/var/lib/postgresql/data:Z
Network={{ podman_network_name }}
PublishPort=5432:5432

Environment=POSTGRES_DB={{ vault_db_name }}
Environment=POSTGRES_USER={{ vault_db_user }}
Secret=db_password,type=env,target=POSTGRES_PASSWORD

HealthCmd=pg_isready -U {{ vault_db_user }}
HealthInterval=10s
HealthTimeout=3s
HealthRetries=3

[Service]
Restart=always
TimeoutStartSec=120

[Install]
WantedBy=default.target
```

### 4. redis (Cache and Broker)

**Purpose**: Deploy Redis container for cache, sessions, Celery, and Channels

**Tasks**:
- Create Redis data volume
- Deploy Quadlet file with custom configuration
- Configure persistence (RDB + AOF)
- Set up authentication (CVE mitigation)
- Configure health checks

**Configuration** (roles/redis/templates/redis.conf.j2):
```conf
# Network
bind 0.0.0.0
port 6379
requirepass {{ vault_redis_password }}

# Persistence
save 900 1
save 300 10
save 60 10000
appendonly yes
appendfsync everysec

# Memory
maxmemory 1gb
maxmemory-policy allkeys-lru

# Security
protected-mode yes
```

### 5. django (Application Server)

**Purpose**: Deploy Daphne ASGI server with Django application

**Tasks**:
- Pull Django image from registry
- Create environment file from template
- Deploy Quadlet file for Daphne
- Run migrations
- Collect static files
- Configure health checks

**Environment Template** (roles/django/templates/env.j2):
```bash
# Django settings
DJANGO_SETTINGS_MODULE={{ django_settings_module }}
SECRET_KEY={{ vault_secret_key }}
FIELD_ENCRYPTION_KEY={{ vault_field_encryption_key }}
ALLOWED_HOSTS={{ allowed_hosts }}

# Database
DB_NAME={{ vault_db_name }}
DB_USER={{ vault_db_user }}
DB_PASSWORD={{ vault_db_password }}
DB_HOST=postgres
DB_PORT=5432

# Redis
REDIS_URL=redis://:{{ vault_redis_password }}@redis:6379/0

# Celery
CELERY_BROKER_URL=redis://:{{ vault_redis_password }}@redis:6379/2
CELERY_RESULT_BACKEND=redis://:{{ vault_redis_password }}@redis:6379/3

# TastyTrade
TASTYTRADE_CLIENT_ID={{ vault_tastytrade_client_id }}
TASTYTRADE_CLIENT_SECRET={{ vault_tastytrade_client_secret }}
TASTYTRADE_BASE_URL=https://api.tastyworks.com

# WebSocket
WS_ALLOWED_ORIGINS={{ allowed_hosts }}

# Email (optional)
{% if vault_email_host_password is defined %}
EMAIL_HOST={{ email_host | default('smtp.gmail.com') }}
EMAIL_PORT={{ email_port | default(587) }}
EMAIL_HOST_USER={{ email_host_user }}
EMAIL_HOST_PASSWORD={{ vault_email_host_password }}
{% endif %}
```

### 6. celery (Background Workers)

**Purpose**: Deploy Celery worker and beat scheduler

**Tasks**:
- Deploy Quadlet files for worker and beat
- Configure queue routing
- Set up resource limits
- Configure logging

**Worker Quadlet** (roles/celery/templates/celery-worker.container.j2):
```ini
[Unit]
Description=Celery Worker
After=redis.service django.service
Requires=redis.service

[Container]
Image={{ django_image }}:{{ django_version }}
ContainerName=celery-worker
Network={{ podman_network_name }}
EnvironmentFile={{ config_dir }}/.env

Exec=celery -A senextrader worker \
    -Q trading,accounts,services \
    -l info \
    --concurrency=4 \
    --max-tasks-per-child=100

[Service]
Restart=always
TimeoutStopSec=300

[Install]
WantedBy=default.target
```

### 7. nginx (Reverse Proxy)

**Purpose**: SSL termination and load balancing

**Tasks**:
- Install Nginx (native, not containerized)
- Configure reverse proxy
- Set up SSL certificates
- Configure WebSocket upgrades
- Set up rate limiting

### 8. letsencrypt (SSL Automation)

**Purpose**: Automate SSL certificate generation and renewal

**Tasks**:
- Install certbot
- Request certificates via HTTP-01 or DNS-01 challenge
- Set up renewal timer
- Configure deploy hooks

### 9. monitoring (Observability)

**Purpose**: Deploy Prometheus and Grafana

**Tasks**:
- Deploy Prometheus container
- Deploy Grafana container
- Configure Django metrics exporter
- Set up dashboards
- Configure alerting

### 10. backup (Data Protection)

**Purpose**: Automated backup execution

**Tasks**:
- Set up backup scripts
- Configure cron jobs
- S3-compatible storage configuration
- Backup verification

## Main Deployment Playbook

**playbooks/deploy.yml**:
```yaml
---
- name: Prepare servers
  hosts: all
  become: true
  roles:
    - common
    - podman

- name: Deploy database
  hosts: database
  become: false
  roles:
    - postgresql

- name: Deploy cache and broker
  hosts: cache
  become: false
  roles:
    - redis

- name: Deploy application
  hosts: webservers
  become: false
  roles:
    - django
    - celery
  tasks:
    - name: Run Django migrations
      containers.podman.podman_container_exec:
        name: django
        command: python manage.py migrate
      register: migrate_result
      changed_when: "'Applying' in migrate_result.stdout"

    - name: Collect static files
      containers.podman.podman_container_exec:
        name: django
        command: python manage.py collectstatic --noinput

- name: Configure reverse proxy
  hosts: webservers
  become: true
  roles:
    - nginx
    - letsencrypt

- name: Set up monitoring
  hosts: webservers
  become: false
  roles:
    - monitoring
  when: enable_monitoring | default(false)

- name: Configure backups
  hosts: all
  become: false
  roles:
    - backup
  when: backup_enabled | default(false)
```

## Running Deployments

### Initial Deployment

```bash
# Install collections
ansible-galaxy collection install -r requirements.yml

# Verify inventory
ansible-inventory -i inventory/production/hosts.yml --list

# Test connectivity
ansible all -i inventory/production/hosts.yml -m ping

# Deploy with vault password
ansible-playbook -i inventory/production/hosts.yml playbooks/deploy.yml --ask-vault-pass

# Or use vault password file
ansible-playbook -i inventory/production/hosts.yml playbooks/deploy.yml --vault-password-file ~/.vault_pass_production
```

### Updates and Redeployments

```bash
# Pull new image and restart services
export IMAGE_TAG=v1.2.3
ansible-playbook -i inventory/production/hosts.yml playbooks/deploy.yml \
  --tags django,celery \
  --vault-password-file ~/.vault_pass_production
```

### Health Checks

```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/health-check.yml
```

## Tagging Strategy

Use tags for granular deployments:

```yaml
roles:
  - { role: django, tags: ['django', 'app'] }
  - { role: celery, tags: ['celery', 'app'] }
  - { role: nginx, tags: ['nginx', 'proxy'] }
  - { role: postgresql, tags: ['postgresql', 'database'] }
```

**Deploy only Django**:
```bash
ansible-playbook playbooks/deploy.yml --tags django
```

## Next Steps

1. **[Configure secrets](./03-SECRETS-MANAGEMENT.md)** with Ansible Vault
2. **[Review service configs](./04-SERVICE-CONFIGURATION.md)** for each role
3. **[Set up networking](./05-NETWORKING-SSL.md)** and SSL
4. **[Begin implementation](./10-IMPLEMENTATION-PHASES.md)** phase-by-phase
