# Senex Trader Deployment Documentation Index

## Overview

Complete deployment documentation for **your-domain.com** production environment using Ansible and Podman.

**Technology**: Django 5.2 + Daphne (ASGI) + PostgreSQL 15 + Redis 7 + Celery + Nginx
**Deployment Method**: Quadlet (systemd) + Manual/Scripted deployment
**Target Environment**: Ubuntu 24.04 LTS
**Security Model**: Rootless containers, SSL/TLS, Let's Encrypt

> **Note**: This index covers both **current operational documentation** (reflecting actual production state as of Oct 2025) and **planning documentation** (original deployment architecture from Oct 2025). For day-to-day operations, use the **Current Operations** section below.

## Quick Navigation

### Current Operations (Production - Oct 2025)

| Need | Document | Location |
|------|----------|----------|
| **Quick commands** | Quick Reference | [QUICK-REFERENCE.md](./QUICK-REFERENCE.md) |
| **⭐ View current deployment state** | Current State | [CURRENT-DEPLOYMENT-STATE.md](./CURRENT-DEPLOYMENT-STATE.md) |
| **⭐ Debug service issues** | Debugging Guide | [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md) |
| **Check service status** | Quick Reference → Check Status | [QUICK-REFERENCE.md#check-service-status](./QUICK-REFERENCE.md#check-service-status) |
| **Deploy new version** | Quick Reference → Deploy | [QUICK-REFERENCE.md#deploy-new-code-version](./QUICK-REFERENCE.md#deploy-new-code-version) |
| **Troubleshoot services** | Debugging Guide → Service Sections | [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md) |

### Planning & Architecture (Reference)

| Need | Document | Location |
|------|----------|----------|
| **Get started** | README | [README.md](./README.md) |
| **Understand architecture** | Overview | [00-OVERVIEW.md](./00-OVERVIEW.md) |
| **Provision servers** | Infrastructure | [01-INFRASTRUCTURE-REQUIREMENTS.md](./01-INFRASTRUCTURE-REQUIREMENTS.md) |
| **Set up Ansible** | Ansible Structure | [02-ANSIBLE-STRUCTURE.md](./02-ANSIBLE-STRUCTURE.md) |
| **Configure secrets** | Secrets Management | [03-SECRETS-MANAGEMENT.md](./03-SECRETS-MANAGEMENT.md) |
| **Copy configs** | Configuration Examples | [configs/](./configs/) |
| **Deploy** | Main Playbook | [ansible/site.yml](./ansible/site.yml) |
| **Validate** | Checklists | [checklists/](./checklists/) |
| **Implementation steps** | Implementation Summary | [IMPLEMENTATION-SUMMARY.md](./IMPLEMENTATION-SUMMARY.md) |

## Directory Structure

```
deployment/
├── README.md                                   # 📘 Main entry point - Quick start guide
├── IMPLEMENTATION-SUMMARY.md                   # Step-by-step implementation workflow
├── DEPLOYMENT-DOCUMENTATION-INDEX.md           # 📑 This file - Complete documentation index
│
├── Core Deployment Guides/
│   ├── 00-OVERVIEW.md                          # 🏗️  Architecture, services, phases, diagrams
│   ├── 01-INFRASTRUCTURE-REQUIREMENTS.md       # 💻 Server specs, costs, network requirements
│   ├── 02-ANSIBLE-STRUCTURE.md                 # Ansible roles, playbooks, collections
│   └── 03-SECRETS-MANAGEMENT.md                # Ansible Vault, credentials, encryption
│
├── ansible/                                    # Ansible Implementation
│   ├── site.yml                                # Main deployment playbook with phase tags
│   ├── requirements.yml                        # (Create) Ansible collections requirements
│   ├── ansible.cfg                             # (Create) Ansible configuration
│   ├── inventory/                              # (Create) Environment-specific inventories
│   │   ├── production/
│   │   │   ├── hosts.yml                       # Production servers
│   │   │   └── group_vars/
│   │   │       ├── all.yml                     # Non-sensitive variables
│   │   │       └── vault.yml                   # Encrypted secrets (Ansible Vault)
│   │   └── staging/
│   │       └── ...                             # Staging environment config
│   └── roles/                                  # Ansible roles (create based on structure)
│       ├── common/                             # System prep, users, firewall
│       ├── podman/                             # Podman installation & config
│       ├── postgresql/                         # PostgreSQL container
│       ├── redis/                              # Redis container
│       ├── django/                             # Django/Daphne container
│       ├── celery/                             # Celery worker & beat
│       └── nginx/                              # Nginx reverse proxy
│
├── configs/                                    # 🔨 Configuration File Examples
│   ├── systemd/                                # systemd Quadlet container definitions
│   │   ├── django.container.example            # Django/Daphne ASGI server
│   │   ├── postgres.container.example          # PostgreSQL database
│   │   ├── redis.container.example             # Redis cache/broker
│   │   ├── celery-worker.container.example     # Celery background worker
│   │   └── celery-beat.container.example       # Celery scheduler
│   ├── nginx/
│   │   └── your-domain.com.conf                # Production Nginx config (SSL, rate limiting)
│   └── redis/
│       └── redis.conf                          # Redis production config (auth, persistence)
│
├── scripts/                                    # 🛠️  Operational Scripts
│   ├── backup-postgresql.sh                    # Daily PostgreSQL backup with S3 upload
│   ├── restore-postgresql.sh                   # Interactive database restoration
│   └── health-check.sh                         # Comprehensive system health validation
│
└── checklists/                                 # Deployment Validation
    ├── pre-deployment-checklist.md             # Infrastructure, secrets, security validation
    └── go-live-checklist.md                    # Step-by-step deployment and verification
```

## File Inventory

### Documentation Files (6)

| File | Lines | Purpose |
|------|-------|---------|
| README.md | ~500 | Main entry point, quick start, architecture overview |
| 00-OVERVIEW.md | ~400 | Architecture diagrams, service topology, deployment phases |
| 01-INFRASTRUCTURE-REQUIREMENTS.md | ~600 | Server specs, network config, costs ($50-$350/month) |
| 02-ANSIBLE-STRUCTURE.md | ~500 | Ansible organization, roles, playbook examples |
| 03-SECRETS-MANAGEMENT.md | ~400 | Vault setup, credential generation, rotation procedures |
| IMPLEMENTATION-SUMMARY.md | ~600 | Step-by-step implementation workflow with commands |

**Total Documentation**: ~3,000 lines

### Configuration Files (10)

| File | Purpose |
|------|---------|
| **Systemd Quadlet (5 files)** | Container service definitions |
| django.container.example | Daphne ASGI server config with health checks |
| postgres.container.example | PostgreSQL with tuning parameters |
| redis.container.example | Redis with persistence and auth |
| celery-worker.container.example | Celery worker with resource limits |
| celery-beat.container.example | Celery beat scheduler |
| **Nginx (1 file)** | Reverse proxy configuration |
| your-domain.com.conf | SSL, HTTP/2, WebSocket, rate limiting |
| **Redis (1 file)** | Cache/broker configuration |
| redis.conf | Authentication, RDB+AOF persistence, memory limits |
| **Ansible (1 file)** | Orchestration playbook |
| site.yml | Main deployment playbook with phase tags |

### Operational Scripts (3)

| Script | Purpose | Schedule |
|--------|---------|----------|
| backup-postgresql.sh | PostgreSQL backup with compression + S3 | Daily 2:00 AM |
| restore-postgresql.sh | Interactive database restoration | On-demand |
| health-check.sh | System health validation (containers, DB, services) | On-demand |

### Checklists (2)

| Checklist | Items | Purpose |
|-----------|-------|---------|
| pre-deployment-checklist.md | ~40 | Infrastructure, security, secrets validation |
| go-live-checklist.md | ~60 | Deployment execution, validation, post-launch |

## Implementation Workflow

### Phase 1: Preparation (Day 1-2)

1. **Read documentation**:
   - Start with [README.md](./README.md)
   - Review [00-OVERVIEW.md](./00-OVERVIEW.md) for architecture
   - Check [01-INFRASTRUCTURE-REQUIREMENTS.md](./01-INFRASTRUCTURE-REQUIREMENTS.md) for server specs

2. **Provision infrastructure**:
   - Provision VPS per requirements (Hetzner CX41 recommended for MVP)
   - Configure DNS (A record: your-domain.com → SERVER_IP)
   - Set up SSH access

3. **Prepare Ansible**:
   - Install Ansible on control machine
   - Copy `ansible/site.yml` to your deployment directory
   - Create inventory structure per [02-ANSIBLE-STRUCTURE.md](./02-ANSIBLE-STRUCTURE.md)

### Phase 2: Configuration (Day 2-3)

1. **Configure secrets**:
   - Follow [03-SECRETS-MANAGEMENT.md](./03-SECRETS-MANAGEMENT.md)
   - Generate encryption keys (Django SECRET_KEY, FIELD_ENCRYPTION_KEY)
   - Create Ansible Vault with credentials

2. **Customize configurations**:
   - Copy Quadlet files from `configs/systemd/` to Ansible role templates
   - Copy Nginx config from `configs/nginx/` to Ansible role templates
   - Update with your domain, registry, and environment-specific values

3. **Review checklists**:
   - Complete `checklists/pre-deployment-checklist.md`
   - Ensure all prerequisites met

### Phase 3: Deployment (Day 3)

1. **Execute deployment**:
   ```bash
   ansible-playbook -i inventory/production/hosts.yml ansible/site.yml \
     --vault-password-file ~/.vault_pass_production \
     --tags phase1
   ```

2. **Validate deployment**:
   - Run `scripts/health-check.sh`
   - Complete `checklists/go-live-checklist.md`
   - Verify all services running

3. **Set up operations**:
   - Configure backup cron jobs (`scripts/backup-postgresql.sh`)
   - Set up external monitoring (UptimeRobot)
   - Document any customizations

### Phase 4: Post-Deployment (Day 4+)

1. **Monitoring**:
   - Verify backups executing (check `/var/backups/postgresql/`)
   - Monitor logs for errors
   - Track resource usage

2. **Optimization**:
   - Review performance metrics
   - Adjust resource limits if needed
   - Plan scaling if necessary

## Key Features

### Security

- **Rootless Podman**: Containers run as unprivileged user
- **Ansible Vault**: AES-256 encrypted secrets
- **SSL/TLS**: HTTPS everywhere, Let's Encrypt automation
- **Redis Auth**: Password protection (CVE-2025-49844 mitigation)
- **HSTS**: HTTP Strict Transport Security (1-year max-age)
- **Rate Limiting**: Login (5/min), API (20/sec), general (10/sec)
- **Security Headers**: CSP, XSS protection, frame denial

### Scalability

- **Phase 1 MVP**: Single server ($50/month) - 1K users
- **Phase 2 Production**: Separated services ($150/month) - 5K users
- **Phase 3 HA**: Multi-server ($350/month) - 20K users
- **Horizontal scaling**: Add Django/Celery instances dynamically
- **Database scaling**: PostgreSQL replication, PgBouncer pooling
- **Cache scaling**: Redis Sentinel for high availability

### Reliability

- **Automated backups**: PostgreSQL (daily), Redis (hourly)
- **Point-in-time recovery**: WAL archiving (5-minute RPO)
- **Health checks**: systemd integration with auto-restart
- **Monitoring**: Prometheus + Grafana (Phase 2+)
- **Disaster recovery**: 30-minute RTO documented procedures

## Technology Decisions

### Why Podman (not Docker)?

- **Rootless by default**: Better security model
- **Daemonless**: No privileged daemon process
- **systemd integration**: Native Quadlet support
- **Drop-in Docker replacement**: Compatible with Docker commands

### Why systemd Quadlet?

- **Declarative**: Container config as systemd unit files
- **Native integration**: systemd manages lifecycle
- **Automatic dependency ordering**: Services start in correct order
- **Health checks**: Integrated with systemd restart policies

### Why Ansible (not Kubernetes)?

- **Simplicity**: No orchestration overhead for single-server MVP
- **Cost-effective**: No control plane resources needed
- **Scalable path**: Can migrate to K8s later if needed
- **Proven pattern**: Reference implementation validated

### Why PostgreSQL 16?

- **Robust**: Industry-standard for Django
- **SSL support**: Encrypted connections
- **Replication**: Streaming replication for HA
- **WAL archiving**: Point-in-time recovery

### Why Redis (not Memcached)?

- **Multi-use**: Cache, sessions, Celery broker, Channels
- **Persistence**: RDB + AOF for durability
- **Pub/Sub**: Built-in for Channels WebSocket
- **Data structures**: Rich types beyond key-value

## Cost Analysis

### Phase 1: MVP ($50/month)

- **VPS**: Hetzner CX41 (4 CPU, 8GB RAM) - $13/month
- **Backups**: Backblaze B2 (50GB) - $0.30/month
- **Domain**: $12/year ≈ $1/month
- **SSL**: Let's Encrypt - Free
- **Monitoring**: Self-hosted - Free
- **Buffer**: $35/month
- **Total**: ~$50/month

### Phase 2: Production ($150/month)

- **Django VPS**: 2 CPU, 4GB - $30/month
- **PostgreSQL VPS**: 2 CPU, 4GB - $40/month
- **Redis/Celery VPS**: 2 CPU, 2GB - $20/month
- **Backups**: B2 (200GB) - $1.20/month
- **Monitoring**: Self-hosted on Django VPS - Free
- **Domain + CDN**: $5/month
- **Buffer**: $53/month
- **Total**: ~$150/month

### Phase 3: High Availability ($350/month)

- **Load Balancer**: Nginx on small VPS - $10/month
- **Django (2x)**: 2 CPU, 4GB each - $60/month
- **PostgreSQL (2x)**: Primary + replica - $100/month
- **Redis Sentinel (3x)**: 1 CPU, 2GB each - $60/month
- **Celery (2x)**: 2 CPU, 2GB each - $60/month
- **Monitoring**: Dedicated (Prometheus/Grafana/Loki) - $30/month
- **Backups**: B2 (500GB) - $3/month
- **CDN + Domain**: $10/month
- **Buffer**: $17/month
- **Total**: ~$350/month

## Support and References

### Documentation

- [Podman Documentation](https://docs.podman.io/)
- [Ansible containers.podman Collection](https://github.com/containers/ansible-podman-collections)
- [Django Deployment Checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [systemd Quadlet Guide](https://www.redhat.com/sysadmin/quadlet-podman)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)

### Reference Implementation

Based on:
- **options_strategy_trader** deployment (Ansible + Docker patterns)
- **Django production best practices** (2025)
- **Podman rootless security model**
- **Senex Trader architecture analysis** (WebSocket, Celery, TastyTrade integration)

## Documentation Status

### Current Operations (Active)

| Document | Status | Last Updated | Purpose |
|----------|--------|--------------|---------|
| QUICK-REFERENCE.md | Active | 2025-10-30 | Quick commands and common tasks |
| CURRENT-DEPLOYMENT-STATE.md | Active | 2025-10-30 | Reflects actual production deployment |
| DEPLOYMENT-DEBUGGING-GUIDE.md | Active | 2025-10-30 | Step-by-step service debugging |

### Planning Documentation (Reference)

| Document | Status | Last Updated | Purpose |
|----------|--------|--------------|---------|
| 00-OVERVIEW.md | Reference | 2025-10-08 | Original architecture planning |
| 01-INFRASTRUCTURE-REQUIREMENTS.md | Reference | 2025-10-08 | Server provisioning guide |
| 02-ANSIBLE-STRUCTURE.md | Reference | 2025-10-08 | Ansible automation structure |
| 03-SECRETS-MANAGEMENT.md | Reference | 2025-10-08 | Secrets and vault management |

**Note**: Planning documentation reflects the original deployment architecture and automation goals. For the actual current deployment state, refer to `CURRENT-DEPLOYMENT-STATE.md`.

## Known Differences: Planning vs Production

The following differences exist between planning documentation (Oct 8) and actual production (Oct 30):

| Aspect | Planned | Actual Production |
|--------|---------|-------------------|
| **PostgreSQL Version** | 16 | 15-alpine |
| **Deployment Path** | `/home/senex/` | `/opt/senex-trader/` |
| **Deployment Method** | Full Ansible automation | Manual/scripted with Quadlet |
| **Ansible Status** | Complete implementation | Structure exists, minimal usage |
| **Monitoring** | Prometheus + Grafana | Watchdog script |
| **Backup Status** | Automated via Ansible | Timer configured but service failing |

See [CURRENT-DEPLOYMENT-STATE.md](./CURRENT-DEPLOYMENT-STATE.md) for complete details.

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2025-10-30 | 2.0 | Added current-state documentation reflecting actual production deployment |
| 2025-10-08 | 1.0 | Initial planning documentation creation |

## Contact and Support

For production issues:
1. **First**: Check [DEPLOYMENT-DEBUGGING-GUIDE.md](./DEPLOYMENT-DEBUGGING-GUIDE.md)
2. **Then**: Review [CURRENT-DEPLOYMENT-STATE.md](./CURRENT-DEPLOYMENT-STATE.md)
3. **Reference**: Consult planning documentation for architecture understanding

For planning new deployments:
1. Review planning documentation (00-OVERVIEW.md through 10-IMPLEMENTATION-PHASES.md)
2. Compare with actual production state in CURRENT-DEPLOYMENT-STATE.md
3. Adapt based on lessons learned

---

**Documentation Status**: Current operations documented | Planning docs for reference
**Last Updated**: 2025-10-30
**Version**: 2.0
