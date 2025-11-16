# Developer Onboarding Guide

## Welcome to Senex Trader Development!

This guide will get you from zero to running the full application locally in Docker containers in about 30 minutes.

---

## Prerequisites

### Required Software

**Check what you have**:
```bash
git --version          # Need: 2.0+
python3 --version      # Need: 3.12+
podman --version       # Need: 4.0+
podman-compose --version  # Need: 1.0+
```

### Install Missing Software

#### macOS
```bash
# Install Homebrew if needed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required tools
brew install git python@3.12 podman podman-compose

# Initialize Podman machine
podman machine init
podman machine start
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install -y git python3.12 podman podman-compose
```

#### Linux (Fedora/RHEL)
```bash
sudo dnf install -y git python3.12 podman podman-compose
```

---

## Step 1: Get the Code (5 minutes)

### Clone Repository

```bash
# Navigate to your projects directory
cd ~/Development  # or wherever you keep projects

# Clone the repository
git clone https://github.com/yourusername/senex_trader.git
cd senex_trader

# Check what branch you're on
git branch
# Should show: * main (or develop)
```

### Verify Files

```bash
# Check that Docker files exist
ls docker/
# Expected: Dockerfile, Dockerfile.dev, entrypoint.sh

ls docker-compose*.yml
# Expected: docker-compose.yml, docker-compose.dev.yml, docker-compose.prod.yml
```

If these files are missing, they haven't been created yet. See `implementation-requirements.md` to create them.

---

## Step 2: Configure Environment (5 minutes)

### Create .env File

```bash
# Copy example file
cp .env.example .env
```

### Edit .env File

**Open in your editor**:
```bash
code .env          # VS Code
vim .env           # Vim
nano .env          # Nano
```

**Set these values** (everything else has defaults):
```bash
# Django Core (use weak keys for dev - these are NOT for production)
SECRET_KEY=django-insecure-dev-key-12345-CHANGE-ME
FIELD_ENCRYPTION_KEY=test-encryption-key-for-development-only

# TastyTrade API (sandbox)
TASTYTRADE_CLIENT_ID=your-sandbox-client-id
TASTYTRADE_CLIENT_SECRET=your-sandbox-client-secret
```

**Where to get TastyTrade sandbox credentials**:
1. Go to https://developer.tastytrade.com
2. Create account / sign in
3. Create sandbox application
4. Copy Client ID and Client Secret

**No real credentials needed for dev!** Sandbox is separate from production.

---

## Step 3: Build Images (5-10 minutes)

### Build Development Images

```bash
# This will take 5-10 minutes the first time (downloading base images, installing packages)
podman-compose -f docker-compose.yml -f docker-compose.dev.yml build
```

**What's happening**:
- Downloading python:3.12-slim-bookworm base image (~120MB)
- Installing system dependencies (PostgreSQL client, etc.)
- Installing Python packages from requirements.txt (~200MB)
- Creating final image (~400-500MB total)

**Expected output**:
```
Building redis
Successfully tagged redis:7-alpine
Building web
Step 1/15 : FROM python:3.12-slim-bookworm
...
Successfully tagged senex_trader:dev
Building celery_worker
...
Build complete!
```

**If build fails**:
- Check your internet connection (downloading packages)
- Check disk space (need ~2GB free)
- See troubleshooting section below

---

## Step 4: Start Services (2 minutes)

### Start Everything

```bash
# Start all services in background (-d = detached)
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

**What's starting**:
- Redis (cache and message broker)
- Django Web Server (http://localhost:8000)
- Celery Worker (background tasks)
- Celery Beat (scheduled tasks)

**Expected output**:
```
Creating senex_redis_dev ... done
Creating senex_web_dev ... done
Creating senex_celery_worker_dev ... done
Creating senex_celery_beat_dev ... done
```

### Watch Startup Logs

```bash
# Watch logs from all services
podman-compose logs -f
```

**Look for these success messages**:
- Redis: "Ready to accept connections"
- Web: "Starting server at http://0.0.0.0:8000"
- Celery Worker: "celery@hostname ready"
- Celery Beat: "Scheduler started"

**Press Ctrl+C to stop watching logs** (services keep running)

### Verify Services Running

```bash
podman-compose ps
```

**Expected output**:
```
NAME                   STATUS    PORTS
senex_redis_dev        Up        6379/tcp
senex_web_dev          Up        0.0.0.0:8000->8000/tcp
senex_celery_worker    Up
senex_celery_beat      Up
```

**All services should show "Up"**. If any show "Exit 1" or "Restarting", see troubleshooting.

---

## Step 5: Initialize Database (3 minutes)

### Run Migrations

```bash
# Apply database migrations (creates tables)
podman-compose exec web python manage.py migrate
```

**Expected output**:
```
Operations to perform:
  Apply all migrations: accounts, admin, auth, contenttypes, sessions, trading
Running migrations:
  Applying accounts.0001_initial... OK
  Applying trading.0001_initial... OK
  ...
```

### Create Superuser

```bash
# Create admin user (interactive)
podman-compose exec web python manage.py createsuperuser
```

**Prompts**:
```
Username: admin
Email address: [email protected]
Password: admin123  (or whatever you want)
Password (again): admin123
Superuser created successfully.
```

**Remember these credentials!** You'll use them to log into the admin interface.

---

## Step 6: Access Application (1 minute)

### Open in Browser

**Main Application**:
- URL: http://localhost:8000
- Expected: Homepage or login page

**Admin Interface**:
- URL: http://localhost:8000/admin
- Login with superuser credentials from Step 5

**Health Check**:
```bash
curl http://localhost:8000/health/
# Expected: {"status": "healthy"}
```

### Success! 🎉

You now have Senex Trader running locally in Docker containers!

---

## Daily Development Workflow

### Starting Your Day

```bash
# Navigate to project
cd ~/Development/senex_trader

# Start services
podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Watch logs (optional)
podman-compose logs -f web
```

### Making Code Changes

**Code changes are live-reloaded!** No need to restart.

1. Edit Python files
2. Save
3. Django auto-reloads
4. Refresh browser

**Exception**: Changes to settings files or models may require:
```bash
# Restart web server
podman-compose restart web

# Or run migrations if you changed models
podman-compose exec web python manage.py makemigrations
podman-compose exec web python manage.py migrate
```

### Running Tests

```bash
# Run all tests
podman-compose exec web pytest

# Run specific test file
podman-compose exec web pytest tests/test_trading.py

# Run with coverage
podman-compose exec web pytest --cov=trading

# Run specific test
podman-compose exec web pytest tests/test_trading.py::test_position_sync
```

### Database Operations

```bash
# Django shell (Python REPL with Django loaded)
podman-compose exec web python manage.py shell

# Create migrations after model changes
podman-compose exec web python manage.py makemigrations

# Apply migrations
podman-compose exec web python manage.py migrate

# Access PostgreSQL directly (dev uses SQLite, but for reference)
podman-compose exec postgres psql -U senex_user -d senex_trader
```

### Viewing Logs

```bash
# All services
podman-compose logs -f

# Single service
podman-compose logs -f web
podman-compose logs -f celery_worker
podman-compose logs -f celery_beat

# Last 100 lines
podman-compose logs --tail=100 web
```

### Ending Your Day

```bash
# Stop all services
podman-compose down

# Or leave them running (they're not using much resources when idle)
```

---

## Common Development Tasks

### Install New Python Package

```bash
# 1. Add to requirements.txt
echo "new-package==1.0.0" >> requirements.txt

# 2. Rebuild web image
podman-compose build web

# 3. Restart web service
podman-compose up -d web
```

### Create New Django App

```bash
# Create app
podman-compose exec web python manage.py startapp myapp

# The files will appear in your local directory (volume mount)
ls myapp/
```

### Reset Database (Start Fresh)

```bash
# WARNING: Deletes all data!

# Stop services
podman-compose down

# Remove database file (dev uses SQLite)
rm db.sqlite3

# Start services
podman-compose up -d

# Run migrations
podman-compose exec web python manage.py migrate

# Create superuser again
podman-compose exec web python manage.py createsuperuser
```

### Access Container Shell

```bash
# Get bash shell inside web container
podman-compose exec web /bin/bash

# Now you're inside the container
whoami  # senex
pwd     # /app
ls      # See project files

# Exit when done
exit
```

### Check Celery Tasks

```bash
# View active tasks
podman-compose exec celery_worker celery -A senex_trader inspect active

# View scheduled tasks
podman-compose exec celery_beat celery -A senex_trader inspect scheduled

# Restart worker (picks up code changes)
podman-compose restart celery_worker
```

---

## Troubleshooting

### Services Won't Start

**Problem**: `podman-compose up -d` fails or services keep restarting

**Check logs**:
```bash
podman-compose logs web
```

**Common causes**:
1. **Port 8000 already in use**
   ```bash
   # Find what's using port 8000
   sudo lsof -i :8000
   # Kill the process or change port in docker-compose.dev.yml
   ```

2. **Missing environment variables**
   ```bash
   # Check .env file exists
   ls -la .env
   # Verify required variables set (SECRET_KEY, etc.)
   cat .env
   ```

3. **Database connection error** (if using PostgreSQL instead of SQLite)
   ```bash
   # Check PostgreSQL is running
   podman-compose ps
   # Wait for it to be healthy
   podman-compose logs postgres
   ```

### Code Changes Not Showing

**Problem**: Changed Python code but website still shows old version

**Solution 1**: Clear browser cache
- Hard refresh: Ctrl+Shift+R (Chrome/Firefox)
- Or open in incognito/private window

**Solution 2**: Restart web server
```bash
podman-compose restart web
```

**Solution 3**: Check for Python errors
```bash
podman-compose logs web
# Look for import errors, syntax errors, etc.
```

### Can't Access http://localhost:8000

**Problem**: Browser shows "Connection refused"

**Check service is running**:
```bash
podman-compose ps
# web service should show "Up" status
```

**Check port mapping**:
```bash
podman-compose ps
# Should show: 0.0.0.0:8000->8000/tcp
```

**Check from command line**:
```bash
curl http://localhost:8000/health/
# Should return: {"status": "healthy"}
```

**Try alternate address**:
```bash
# Sometimes localhost doesn't resolve correctly
curl http://127.0.0.1:8000/health/
```

### Tests Failing

**Problem**: `pytest` command fails or tests error

**Common causes**:

1. **Database not migrated**
   ```bash
   podman-compose exec web python manage.py migrate
   ```

2. **Missing test dependencies**
   ```bash
   # Check pytest is installed
   podman-compose exec web pip list | grep pytest
   ```

3. **Test database issues**
   ```bash
   # Django creates test database automatically, but may need permissions
   # Check test settings in senex_trader/settings/development.py
   ```

### Build Fails

**Problem**: `podman-compose build` exits with error

**Common causes**:

1. **Network issues**
   ```bash
   # Test internet connection
   ping -c 3 google.com
   # Test can reach pypi
   ping -c 3 pypi.org
   ```

2. **Disk space**
   ```bash
   df -h
   # Need at least 2GB free
   ```

3. **Syntax error in Dockerfile**
   ```bash
   # Check Dockerfile syntax
   cat docker/Dockerfile
   # Look for typos, missing quotes, etc.
   ```

### Get Help

**Check documentation**:
1. `initialization-checklist.md` - Detailed troubleshooting
2. `quick-reference.md` - Common commands
3. `architecture.md` - System design

**Ask team**:
- Slack: #senex-trader-dev channel
- Email: dev-team@your-domain.com

**Check logs**:
```bash
# Always start with logs
podman-compose logs -f
```

---

## Development Tools Setup

### VS Code Integration

**Install extensions**:
- Python
- Docker
- Remote - Containers

**Open project in VS Code**:
```bash
code .
```

**Python interpreter**: Point to Python inside container
1. Ctrl+Shift+P → "Python: Select Interpreter"
2. Choose "Docker" option
3. Select `senex_trader:dev`

### PyCharm Integration

**Configure Docker**:
1. File → Settings → Build, Execution, Deployment → Docker
2. Add Docker connection (use Podman socket)
3. Configure Python interpreter to use Docker

### Git Workflow

**Create feature branch**:
```bash
git checkout -b feature/my-new-feature
```

**Make changes, commit**:
```bash
git add .
git commit -m "Add new feature"
```

**Push to remote**:
```bash
git push origin feature/my-new-feature
```

**Create pull request on GitHub/GitLab**

---

## Best Practices

### Development Environment

✅ **DO**:
- Keep .env file for local development
- Use weak secrets in development (not real credentials)
- Commit code regularly
- Run tests before committing
- Use feature branches
- Keep docker-compose.dev.yml for development only

❌ **DON'T**:
- Don't commit .env file (it's in .gitignore)
- Don't use production credentials locally
- Don't commit directly to main branch
- Don't push broken code
- Don't modify production files for local testing

### Code Quality

**Before committing**:
```bash
# Run tests
podman-compose exec web pytest

# Check code style (if using ruff/black)
podman-compose exec web ruff check .
podman-compose exec web black --check .

# Run migrations check
podman-compose exec web python manage.py makemigrations --check --dry-run
```

### Container Management

**Keep containers clean**:
```bash
# Weekly: Remove unused images
podman image prune -f

# Monthly: Remove unused volumes (careful!)
podman volume prune -f

# Check disk usage
podman system df
```

---

## Advanced Topics

### Debugging with pdb

**Add breakpoint in code**:
```python
import pdb; pdb.set_trace()
```

**Attach to running container**:
```bash
# Stop web service first
podman-compose stop web

# Start web in foreground (to see pdb prompt)
podman-compose run --rm --service-ports web
```

### Hot Reload for Frontend

**If using frontend framework** (React, Vue, etc.):
```yaml
# In docker-compose.dev.yml, add to web service:
volumes:
  - ./frontend/src:/app/frontend/src
```

**Restart to apply**:
```bash
podman-compose restart web
```

### Custom Django Commands

**Create command**:
```bash
# Create management command
mkdir -p myapp/management/commands
touch myapp/management/commands/__init__.py
touch myapp/management/commands/my_command.py
```

**Run command**:
```bash
podman-compose exec web python manage.py my_command
```

---

## Next Steps

Now that you're set up:

1. **Read the codebase**:
   - `senex_trader/` - Django project settings
   - `accounts/` - User authentication
   - `trading/` - Trading logic
   - `services/` - Business logic

2. **Pick up a task**:
   - Check project board (Jira, GitHub Issues, etc.)
   - Start with "good first issue" tags
   - Ask team lead for recommendations

3. **Learn the architecture**:
   - Read `architecture.md` in this directory
   - Understand service interactions
   - Learn data models

4. **Contribute**:
   - Create feature branch
   - Write tests for new code
   - Submit pull request
   - Respond to code review

---

## Useful Aliases

**Add to your ~/.bashrc or ~/.zshrc**:

```bash
# Senex Trader shortcuts
alias st-start='cd ~/Development/senex_trader && podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d'
alias st-stop='cd ~/Development/senex_trader && podman-compose down'
alias st-logs='cd ~/Development/senex_trader && podman-compose logs -f'
alias st-shell='cd ~/Development/senex_trader && podman-compose exec web python manage.py shell'
alias st-test='cd ~/Development/senex_trader && podman-compose exec web pytest'
alias st-migrate='cd ~/Development/senex_trader && podman-compose exec web python manage.py migrate'

# Docker/Podman
alias docker='podman'
alias docker-compose='podman-compose'
```

**Reload shell**:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

**Usage**:
```bash
st-start    # Start Senex Trader
st-logs     # View logs
st-shell    # Django shell
st-test     # Run tests
st-stop     # Stop services
```

---

## Resources

**Internal Documentation**:
- `README.md` - This directory's index
- `quick-reference.md` - Command cheat sheet
- `architecture.md` - System design
- `implementation-requirements.md` - Code structure

**External Documentation**:
- Django: https://docs.djangoproject.com/
- Celery: https://docs.celeryproject.org/
- Channels: https://channels.readthedocs.io/
- TastyTrade API: https://developer.tastytrade.com/
- Podman: https://docs.podman.io/

**Team Resources**:
- Wiki: https://wiki.your-domain.com
- Slack: #senex-trader-dev
- Daily Standup: 10 AM daily

---

## Congratulations! 🎉

You're now set up and ready to develop on Senex Trader!

**Questions?** Ask in #senex-trader-dev Slack channel or email dev-team@your-domain.com

**Happy coding!** 🚀
