# Docker/Podman Quick Reference

## Essential Commands Cheat Sheet

---

## Build Commands

```bash
# Build production image
podman build -t senex_trader:latest .

# Build with specific Dockerfile
podman build -f docker/Dockerfile -t senex_trader:latest .

# Build with cache
podman build --layers -t senex_trader:latest .

# Build without cache
podman build --no-cache -t senex_trader:latest .

# Build and tag multiple versions
podman build -t senex_trader:1.0.0 -t senex_trader:latest .
```

---

## Development Workflow

```bash
# Start development environment
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Start in background
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Stop all services
podman-compose down

# Rebuild and restart
podman-compose build && podman-compose up -d

# View logs (all services)
podman-compose logs -f

# View logs (single service)
podman-compose logs -f web

# Execute command in running container
podman-compose exec web python manage.py shell
```

---

## Production Workflow

```bash
# Start production environment
podman-compose --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d

# Stop production services
podman-compose -f docker-compose.yml -f docker-compose.prod.yml down

# View service status
podman-compose ps

# Restart single service
podman-compose restart web

# Scale services
podman-compose up -d --scale web=3 --scale celery_worker=4
```

---

## Image Management

```bash
# List images
podman images

# Tag image
podman tag senex_trader:latest myregistry.com/senex_trader:1.0.0

# Push to registry
podman push myregistry.com/senex_trader:1.0.0

# Pull from registry
podman pull myregistry.com/senex_trader:1.0.0

# Remove image
podman rmi senex_trader:latest

# Remove all dangling images
podman image prune -f

# Check image size
podman images senex_trader:latest --format "{{.Size}}"
```

---

## Container Management

```bash
# List running containers
podman ps

# List all containers (including stopped)
podman ps -a

# Stop container
podman stop senex_web

# Remove container
podman rm senex_web

# View container logs
podman logs -f senex_web

# Execute command in container
podman exec -it senex_web /bin/bash

# Check container stats
podman stats --no-stream

# Inspect container
podman inspect senex_web
```

---

## Django Management Commands

```bash
# Run migrations
podman-compose exec web python manage.py migrate

# Create superuser
podman-compose exec web python manage.py createsuperuser

# Collect static files
podman-compose exec web python manage.py collectstatic --noinput

# Django shell
podman-compose exec web python manage.py shell

# Run tests
podman-compose exec web pytest

# Check configuration
podman-compose exec web python manage.py check
```

---

## Database Operations

```bash
# Connect to PostgreSQL
podman-compose exec postgres psql -U senex_user -d senex_trader

# Backup database
podman-compose exec -T postgres pg_dump -U senex_user senex_trader | gzip > backup.sql.gz

# Restore database
gunzip -c backup.sql.gz | podman-compose exec -T postgres psql -U senex_user senex_trader

# List tables
podman-compose exec postgres psql -U senex_user -d senex_trader -c "\dt"

# Check database connection
podman-compose exec postgres pg_isready -U senex_user -d senex_trader
```

---

## Redis Operations

```bash
# Connect to Redis CLI
podman-compose exec redis redis-cli

# Ping Redis
podman-compose exec redis redis-cli ping

# Check Redis keys
podman-compose exec redis redis-cli DBSIZE

# Flush Redis (WARNING: deletes all data)
podman-compose exec redis redis-cli FLUSHALL
```

---

## Celery Operations

```bash
# Check Celery worker status
podman-compose exec celery_worker celery -A senex_trader inspect active

# Check scheduled tasks
podman-compose exec celery_beat celery -A senex_trader inspect scheduled

# Restart Celery worker
podman-compose restart celery_worker

# Restart Celery beat
podman-compose restart celery_beat

# View Celery logs
podman-compose logs -f celery_worker
```

---

## Volume Management

```bash
# List volumes
podman volume ls

# Inspect volume
podman volume inspect postgres_data

# Create volume
podman volume create postgres_data

# Remove volume (WARNING: deletes data)
podman volume rm postgres_data

# Export volume to tarball
podman volume export postgres_data -o postgres_backup.tar

# Import volume from tarball
podman volume import postgres_data postgres_backup.tar

# Remove all unused volumes
podman volume prune -f
```

---

## Network Management

```bash
# List networks
podman network ls

# Inspect network
podman network inspect senex_network

# Create network
podman network create senex_network

# Remove network
podman network rm senex_network
```

---

## Health Checks

```bash
# Check all container health
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Health}}"

# Test health endpoint
curl http://localhost:8000/health/

# Check specific container health
podman inspect --format='{{json .State.Health}}' senex_web | jq
```

---

## Troubleshooting

```bash
# View all logs with timestamps
podman-compose logs -f --timestamps

# View last 100 lines of logs
podman-compose logs --tail=100 web

# Check container resource usage
podman stats

# Inspect container configuration
podman inspect senex_web | jq

# Check if ports are in use
sudo lsof -i :8000

# Test network connectivity (from web to postgres)
podman-compose exec web nc -zv postgres 5432

# Test network connectivity (from web to redis)
podman-compose exec web nc -zv redis 6379

# Enter container shell for debugging
podman-compose exec web /bin/bash

# Run container with custom command
podman run -it --rm senex_trader:latest /bin/bash
```

---

## Secret Generation

```bash
# Generate Django SECRET_KEY
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Generate FIELD_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate DB_PASSWORD
openssl rand -base64 32

# Generate random string
openssl rand -hex 32
```

---

## Systemd Integration (Production)

```bash
# Generate systemd unit files
podman generate systemd --name senex_web --files --new

# Install systemd units (user)
mkdir -p ~/.config/systemd/user/
cp container-*.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable service
systemctl --user enable container-senex_web.service

# Start service
systemctl --user start container-senex_web.service

# Check service status
systemctl --user status container-senex_web.service

# View service logs
journalctl --user -u container-senex_web.service -f

# Enable linger (start without login)
loginctl enable-linger $USER
```

---

## Performance Testing

```bash
# Load test health endpoint
ab -n 1000 -c 10 http://localhost:8000/health/

# Monitor real-time container stats
podman stats

# Check image layers
podman history senex_trader:latest

# Analyze image with dive
dive senex_trader:latest
```

---

## CI/CD Helpers

```bash
# Build with version from git
VERSION=$(git describe --tags --always)
podman build -t senex_trader:$VERSION .

# Tag with multiple tags
podman tag senex_trader:1.0.0 senex_trader:1.0
podman tag senex_trader:1.0.0 senex_trader:1
podman tag senex_trader:1.0.0 senex_trader:latest

# Push all tags
podman push senex_trader:1.0.0
podman push senex_trader:1.0
podman push senex_trader:1
podman push senex_trader:latest

# Scan for vulnerabilities
trivy image senex_trader:latest
```

---

## Environment Variables

```bash
# Development (.env)
ENVIRONMENT=development
SECRET_KEY=dev-key
DB_HOST=localhost
REDIS_URL=redis://127.0.0.1:6379/1

# Production (.env.production)
ENVIRONMENT=production
SECRET_KEY=<GENERATE>
DB_HOST=postgres
DB_PASSWORD=<GENERATE>
REDIS_URL=redis://redis:6379/0
```

---

## Common File Paths

```bash
# Project root
/app/

# Static files
/app/staticfiles/

# Logs
/var/log/senex_trader/

# Media files
/app/media/

# Celery beat schedule
/app/celerybeat-schedule

# Entrypoint script
/entrypoint.sh
```

---

## Quick Start (Development)

```bash
# 1. Create .env file
cp .env.example .env

# 2. Build images
podman-compose -f docker-compose.yml -f docker-compose.dev.yml build

# 3. Start services
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 4. Create superuser
podman-compose exec web python manage.py createsuperuser

# 5. Access application
open http://localhost:8000
```

---

## Quick Start (Production)

```bash
# 1. Generate secrets
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())" > secret_key.txt
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > encryption_key.txt

# 2. Create .env.production
cp .env.production.example .env.production
# Edit .env.production with generated secrets

# 3. Build images
podman-compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml build

# 4. Start services
podman-compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml up -d

# 5. Create superuser
podman-compose exec web python manage.py createsuperuser

# 6. Verify health
curl http://localhost:8000/health/
```

---

## Emergency Procedures

```bash
# STOP ALL SERVICES IMMEDIATELY
podman-compose down

# RESTART ALL SERVICES
podman-compose up -d

# ROLLBACK TO PREVIOUS VERSION
podman pull myregistry.com/senex_trader:1.0.0
podman tag myregistry.com/senex_trader:1.0.0 senex_trader:latest
podman-compose up -d --force-recreate

# RESTORE DATABASE FROM BACKUP
podman-compose down
gunzip -c backup.sql.gz | podman-compose exec -T postgres psql -U senex_user senex_trader
podman-compose up -d

# CLEAR ALL DATA AND START FRESH (WARNING: DESTRUCTIVE)
podman-compose down -v
podman-compose up -d
```

---

## Aliases (Add to ~/.bashrc or ~/.zshrc)

```bash
# Docker → Podman aliases
alias docker='podman'
alias docker-compose='podman-compose'

# Senex Trader shortcuts
alias senex-dev='podman-compose -f docker-compose.yml -f docker-compose.dev.yml'
alias senex-prod='podman-compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml'
alias senex-logs='podman-compose logs -f'
alias senex-shell='podman-compose exec web python manage.py shell'
alias senex-migrate='podman-compose exec web python manage.py migrate'
alias senex-test='podman-compose exec web pytest'
```

**Usage after adding aliases**:
```bash
senex-dev up        # Start development
senex-prod up -d    # Start production
senex-logs web      # View web logs
senex-shell         # Django shell
senex-migrate       # Run migrations
senex-test          # Run tests
```

---

## Port Reference

| Service | Internal Port | External Port (Dev) | External Port (Prod) |
|---------|---------------|---------------------|---------------------|
| Django Web | 8000 | 8000 | - (via reverse proxy) |
| PostgreSQL | 5432 | 5432 (optional) | - (internal only) |
| Redis | 6379 | 6379 (optional) | - (internal only) |

---

## Service Names (for internal networking)

- `postgres` - PostgreSQL database
- `redis` - Redis cache/broker
- `web` - Django web server
- `celery_worker` - Celery worker
- `celery_beat` - Celery beat scheduler

**Example connection strings**:
- Database: `postgresql://senex_user:password@postgres:5432/senex_trader`
- Redis: `redis://redis:6379/0`

---

## Key Documentation Files

- `architecture.md` - System design
- `dockerfile-design.md` - Image design
- `docker-compose-strategy.md` - Orchestration
- `environment-variables.md` - All variables
- `build-workflow.md` - Build/push process
- `initialization-checklist.md` - Deployment steps
- `implementation-requirements.md` - Code changes needed
- `podman-migration.md` - Podman guide
- `developer-onboarding.md` - New developer setup

---

## Help

For detailed documentation, see README.md or specific topic files.

For issues, check `initialization-checklist.md` troubleshooting section.
