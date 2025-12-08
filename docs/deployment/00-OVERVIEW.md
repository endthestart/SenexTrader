# Senex Trader Production Deployment - Overview

## Purpose

Guide for deploying Senex Trader to production using Ansible and Podman.

Design goals:
- **Secure**: Secrets encrypted, SSL/TLS everywhere, rootless containers
- **Scalable**: Start simple, grow incrementally as traffic increases
- **Reliable**: Automated backups, health checks, disaster recovery
- **Cost-Effective**: Optimized resource usage with clear scaling paths

## Technology Stack

### Container Platform
- **Podman 5.0+** (rootless) - Secure, daemonless container runtime
- **systemd Quadlet** - Native systemd integration for container management
- **Podman Networks** - DNS-based service discovery

### Orchestration
- **Ansible 2.15+** - Infrastructure as code
- **Ansible Collections**:
  - `containers.podman` (v1.17.0+) - Container management
  - `community.crypto` - SSL/TLS automation
  - `ansible.posix` - System configuration

### Application Services

| Service | Technology | Purpose | Port |
|---------|-----------|---------|------|
| **Web/WebSocket** | Daphne (ASGI) | Django HTTP + WebSocket server | 8000 |
| **Database** | PostgreSQL 16 | Primary data store with SSL | 5432 |
| **Cache/Broker** | Redis 7 | Cache, sessions, Celery, channels | 6379 |
| **Background Jobs** | Celery Worker | Async task execution | - |
| **Task Scheduler** | Celery Beat | Scheduled trading tasks | - |
| **Reverse Proxy** | Nginx 1.25 | SSL termination, load balancing | 80, 443 |

### Monitoring & Operations
- **Prometheus + Grafana** - Metrics and dashboards
- **Grafana Loki** - Log aggregation (optional)
- **systemd** - Service management and health checks
- **Let's Encrypt** - SSL certificate automation

## Architecture Diagram

```
                             Internet
                                |
                        [your-domain.com]
                                |
                          +-----+-----+
                          |   Nginx   |  (SSL termination)
                          |   :443    |  (Load balancing)
                          +-----------+
                                |
                    +-----------+-----------+
                    |                       |
              +-----+-----+           +-----+-----+
              |  Daphne 1 |           |  Daphne 2 |  (WebSocket + HTTP)
              |   :8001   |           |   :8002   |  (ASGI server)
              +-----------+           +-----------+
                    |                       |
                    +----------+------------+
                               |
                      [Podman Network: senex_net]
                               |
          +--------------------+--------------------+
          |                    |                    |
    +-----+-----+      +-------+-------+    +-------+-------+
    | PostgreSQL|      |     Redis     |    |    Celery     |
    |   :5432   |      |     :6379     |    |   Workers     |
    |  (SSL)    |      | (4 databases) |    | + Beat Sched. |
    +-----------+      +---------------+    +---------------+
          |                    |                    |
    [Persistent]         [Persistent]         [Stateless]
     Volume: DB          Volume: Redis         (shares code)

External Dependencies:
- TastyTrade API (OAuth, market data, order execution)
- DXFeed Streaming (real-time quotes via TastyTrade)
```

## Service Dependencies

### Redis Database Usage
Redis hosts 4 separate logical databases:

- **DB 0**: Django cache (option chains, account state)
- **DB 1**: Django Channels (WebSocket messages)
- **DB 2**: Celery broker (task queue)
- **DB 3**: Celery result backend

### Critical Service Ordering

1. **PostgreSQL** must start first (schema, user data)
2. **Redis** must start second (cache, broker, channels)
3. **Django/Daphne** starts after DB + Redis (migrations run)
4. **Celery Worker** starts after Redis (connects to broker)
5. **Celery Beat** starts last (schedules tasks)
6. **Nginx** can start independently (reverse proxy)

## Deployment Phases

### Phase 1: MVP Single Server ($50/month)
- **Timeline**: Week 1-2
- **Capacity**: 1,000 users, 500 trades/day
- **Components**: All services on 1 VPS (4 CPU, 8GB RAM)
- **HA**: None (single point of failure)

### Phase 2: Production Ready ($150/month)
- **Timeline**: Week 3-4
- **Capacity**: 5,000 users, 2,000 trades/day
- **Components**: Separated services, PgBouncer, monitoring
- **HA**: Automated backups, health checks

### Phase 3: High Availability ($350/month)
- **Timeline**: Week 5-8
- **Capacity**: 20,000 users, 10,000 trades/day
- **Components**: Redundant Django/Daphne, PostgreSQL replica, Redis Sentinel
- **HA**: 99.9% uptime target, automated failover

## Security Model

### Secrets Management
- **Ansible Vault**: Encrypted secret storage in version control
- **Environment Variables**: Secrets injected at runtime
- **Encryption Keys**: Fernet keys for Django encrypted fields
- **OAuth Tokens**: TastyTrade credentials encrypted in database

### Network Security
- **Rootless Podman**: Containers run as unprivileged user
- **SELinux**: Enabled for container isolation
- **Firewall**: Only ports 22, 80, 443 exposed externally
- **Internal Network**: Services communicate via Podman bridge network

### Application Security
- **SSL/TLS**: HTTPS everywhere, HTTP→HTTPS redirect
- **HSTS**: Strict transport security enabled
- **CSRF**: Django CSRF protection
- **WebSocket Origin Validation**: Restrict WS connections to known domains

## Data Flow

### Trading Execution Flow
```
User Browser → Nginx → Daphne → Django View
                                    ↓
                            Celery Task (execute_order)
                                    ↓
                            TastyTrade API (OAuth)
                                    ↓
                            Order Confirmation
                                    ↓
                            PostgreSQL (store trade)
                                    ↓
                            WebSocket Update (via Channels)
                                    ↓
                            User Browser (real-time notification)
```

### Scheduled Task Flow
```
Celery Beat → Task Schedule → Celery Worker
                                    ↓
                            sync_positions_task
                                    ↓
                            TastyTrade API
                                    ↓
                            PostgreSQL (update positions)
                                    ↓
                            Redis (invalidate cache)
```

### Real-Time Streaming Flow
```
TastyTrade DXFeed → StreamManager → Redis Channels → Daphne → WebSocket → Browser
                                          ↓
                                    (broadcast to all connected clients)
```

## Resource Requirements by Phase

### Phase 1: Single VPS
- **CPU**: 4 cores
- **RAM**: 8GB
- **Storage**: 80GB SSD
- **Network**: 1TB/month bandwidth
- **Estimated Cost**: $40-60/month (Hetzner CX41, DigitalOcean)

### Phase 2: Separated Services
- **Django/Nginx**: 2 CPU, 4GB RAM ($30/month)
- **PostgreSQL**: 2 CPU, 4GB RAM ($40/month)
- **Redis/Celery**: 2 CPU, 2GB RAM ($20/month)
- **Backups**: S3-compatible storage ($5/month)
- **Monitoring**: Self-hosted on Django VPS (free)
- **Estimated Cost**: $120-150/month

### Phase 3: High Availability
- **Django/Nginx**: 2x instances ($60/month)
- **PostgreSQL**: Primary + replica ($100/month)
- **Redis**: Sentinel cluster 3x ($60/month)
- **Celery**: 2x workers ($60/month)
- **PgBouncer**: Shared with PostgreSQL
- **Monitoring/Logging**: Dedicated ($30/month)
- **Estimated Cost**: $300-350/month

## Operational Characteristics

### Backup Strategy
- **PostgreSQL**: WAL archiving + daily base backups (30-day retention)
- **Redis**: RDB snapshots + AOF log (7-day retention)
- **Media Files**: Daily rsync to S3 (30-day retention)
- **Recovery Point Objective (RPO)**: 5 minutes
- **Recovery Time Objective (RTO)**: 30 minutes

### Monitoring Metrics
- **Application**: Request rate, latency, error rate
- **Database**: Connection pool usage, query performance, replication lag
- **Cache**: Hit rate, memory usage, eviction rate
- **Celery**: Queue length, task success/failure rate, execution time
- **WebSocket**: Connection count, message throughput
- **System**: CPU, memory, disk I/O, network bandwidth

### Scaling Triggers
- **Add Django instance**: CPU >70% for 5 minutes
- **Add PostgreSQL replica**: CPU >80% for 10 minutes
- **Add Celery worker**: Queue length >100 for 5 minutes
- **Upgrade Redis**: Memory >90% usage
- **Add Daphne instance**: WebSocket connections >1500/instance

## Documentation Navigation

Read the guides in order for initial deployment:

1. **[01-INFRASTRUCTURE-REQUIREMENTS.md](01-INFRASTRUCTURE-REQUIREMENTS.md)** - Server setup and prerequisites
2. **[02-ANSIBLE-STRUCTURE.md](02-ANSIBLE-STRUCTURE.md)** - Ansible organization and roles
3. **[03-SECRETS-MANAGEMENT.md](03-SECRETS-MANAGEMENT.md)** - Credential and key management
4. **[04-SERVICE-CONFIGURATION.md](04-SERVICE-CONFIGURATION.md)** - Service-specific configs
5. **[05-NETWORKING-SSL.md](05-NETWORKING-SSL.md)** - Network and SSL/TLS setup
6. **[06-SECURITY-HARDENING.md](06-SECURITY-HARDENING.md)** - Production security checklist
7. **[07-MONITORING-LOGGING.md](07-MONITORING-LOGGING.md)** - Observability setup
8. **[08-BACKUP-DISASTER-RECOVERY.md](08-BACKUP-DISASTER-RECOVERY.md)** - Backup and DR procedures
9. **[09-SCALING-STRATEGY.md](09-SCALING-STRATEGY.md)** - Horizontal scaling guide
10. **[10-IMPLEMENTATION-PHASES.md](10-IMPLEMENTATION-PHASES.md)** - Week-by-week rollout plan

## Reference Implementation

This deployment approach is based on:
- **options_strategy_trader** reference deployment (Ansible + Docker patterns)
- **2025 best practices** for Django + Podman (rootless, Quadlet)
- **Senex Trader architecture** analysis (WebSocket, Celery, TastyTrade integration)
- **Production security standards** (SOC 2, financial data compliance)

## Key Principles

1. **Infrastructure as Code**: All configuration in version control
2. **Immutable Infrastructure**: Containers rebuilt, not patched
3. **Declarative Configuration**: Quadlet files define desired state
4. **Defense in Depth**: Multiple security layers
5. **Fail Fast**: Health checks with automatic restart
6. **Observability**: Comprehensive logging and metrics
7. **Cost Optimization**: Start small, scale incrementally
8. **Disaster Recovery**: Tested backup and restoration procedures

## Next Steps

1. Review infrastructure requirements and provision servers
2. Set up Ansible control machine
3. Configure secrets and environment variables
4. Deploy Phase 1 (single server MVP)
5. Validate security and monitoring
6. Execute go-live checklist
