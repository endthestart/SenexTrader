# Build Workflow

## Overview

This document defines the complete workflow for building, tagging, testing, and pushing Senex Trader container images using Podman. It covers local development builds, CI/CD integration, and production image management.

---

## Build Commands Reference

### Basic Build

**Minimal Build**:
```bash
podman build -t senex_trader:latest .
```

**Production Build** (from project root):
```bash
podman build \
  -f docker/Dockerfile \
  -t senex_trader:latest \
  .
```

**Development Build**:
```bash
podman build \
  -f docker/Dockerfile.dev \
  -t senex_trader:dev \
  .
```

### Build with Cache

**Enable Layer Caching**:
```bash
podman build --layers -t senex_trader:latest .
```

**Note**: Podman's support for `--cache-to` and `--cache-from` flags varies by version. These are BuildKit features that may require Podman 4.4+ with Buildah backend.

**Alternative: Use `--layers` for built-in caching** (recommended for Podman):
```bash
# Podman caches layers automatically with --layers flag
podman build --layers -t senex_trader:latest .

# Subsequent builds reuse cached layers automatically
podman build --layers -t senex_trader:latest .
```

**Advanced: External Cache** (if using Podman 4.4+):
```bash
# Export cache (check Podman version supports this)
podman build \
  --layers \
  --cache-to type=local,dest=/tmp/buildcache \
  -t senex_trader:latest \
  .

# Import cache
podman build \
  --layers \
  --cache-from type=local,src=/tmp/buildcache \
  -t senex_trader:latest \
  .
```

**Verify your Podman version**:
```bash
podman --version
# If < 4.4, use --layers only (built-in caching)
# If >= 4.4, can try --cache-to/--cache-from
```

### Build with Build Arguments

**Set Python Version**:
```bash
podman build \
  --build-arg PYTHON_VERSION=3.12 \
  -t senex_trader:latest \
  .
```

**Set Environment**:
```bash
podman build \
  --build-arg ENVIRONMENT=production \
  -t senex_trader:latest \
  .
```

### No-Cache Build

**Force Rebuild** (ignore all cache):
```bash
podman build --no-cache -t senex_trader:latest .
```

**Note**: Podman does not support `--no-cache-filter` for rebuilding specific stages (Docker BuildKit feature). To rebuild from a specific stage, use `--no-cache` to rebuild everything.

---

## Image Tagging Strategy

### Semantic Versioning

**Format**: `MAJOR.MINOR.PATCH`

**Examples**:
- `1.0.0` - Initial release
- `1.1.0` - New features
- `1.1.1` - Bug fixes
- `2.0.0` - Breaking changes

### Recommended Tagging Scheme

**Multiple Tags for Single Image**:
```bash
# Build with specific version
podman build -t senex_trader:1.2.3 .

# Add latest tag
podman tag senex_trader:1.2.3 senex_trader:latest

# Add minor version tag (1.2)
podman tag senex_trader:1.2.3 senex_trader:1.2

# Add major version tag (1)
podman tag senex_trader:1.2.3 senex_trader:1

# Add git commit SHA
podman tag senex_trader:1.2.3 senex_trader:$(git rev-parse --short HEAD)

# Add date tag
podman tag senex_trader:1.2.3 senex_trader:$(date +%Y%m%d)
```

**Result**: Single image with multiple tags for different use cases

### Tag Naming Conventions

| Tag Pattern | Use Case | Example |
|-------------|----------|---------|
| `latest` | Latest stable release | `senex_trader:latest` |
| `1.2.3` | Specific version | `senex_trader:1.2.3` |
| `1.2` | Latest patch of minor | `senex_trader:1.2` |
| `1` | Latest minor of major | `senex_trader:1` |
| `abc123f` | Git commit SHA | `senex_trader:abc123f` |
| `20250115` | Build date | `senex_trader:20250115` |
| `dev` | Development builds | `senex_trader:dev` |
| `staging` | Staging builds | `senex_trader:staging` |
| `pr-123` | Pull request builds | `senex_trader:pr-123` |

### Registry Tagging

**Full Registry Path**:
```bash
# Local build
podman build -t senex_trader:1.2.3 .

# Tag for registry
podman tag senex_trader:1.2.3 myregistry.com/senex_trader:1.2.3
podman tag senex_trader:1.2.3 myregistry.com/senex_trader:latest

# Or build with full path directly
podman build -t myregistry.com/senex_trader:1.2.3 .
```

---

## Image Testing

### Smoke Tests

#### 1. Verify Image Exists

```bash
podman images | grep senex_trader
# senex_trader  latest  abc123  2 minutes ago  450 MB
```

#### 2. Check Image Size

```bash
podman images senex_trader:latest --format "{{.Size}}"
# 450 MB (target: <500 MB)
```

#### 3. Inspect Image Metadata

```bash
podman inspect senex_trader:latest | jq '.[0].Config.Labels'
# {
#   "org.opencontainers.image.version": "1.2.3",
#   "org.opencontainers.image.created": "2025-01-15T10:30:00Z",
#   ...
# }
```

#### 4. Test Django Check Command

```bash
podman run --rm \
  -e SECRET_KEY=test-secret-key \
  -e FIELD_ENCRYPTION_KEY=test-encryption-key \
  senex_trader:latest \
  python manage.py check
# System check identified no issues (0 silenced).
```

#### 5. Test Migrations (Dry Run)

```bash
podman run --rm \
  -e SECRET_KEY=test-secret-key \
  -e FIELD_ENCRYPTION_KEY=test-encryption-key \
  senex_trader:latest \
  python manage.py migrate --plan
# Planned operations:
# ...
```

#### 6. Test Entry Point Routing

**Test web service**:
```bash
podman run --rm senex_trader:latest web --help
# Usage: daphne [OPTIONS] application
```

**Test celery worker**:
```bash
podman run --rm senex_trader:latest celery-worker --help
# Usage: celery [OPTIONS] worker [WORKER_OPTIONS]
```

**Test celery beat**:
```bash
podman run --rm senex_trader:latest celery-beat --help
# Usage: celery [OPTIONS] beat [BEAT_OPTIONS]
```

---

## Automated Build Script

### Makefile

**Create Makefile in project root**:

```makefile
.PHONY: build build-dev tag push test clean

# Variables
VERSION := $(shell git describe --tags --always --dirty)
COMMIT := $(shell git rev-parse --short HEAD)
DATE := $(shell date +%Y%m%d)
REGISTRY := myregistry.com
IMAGE := senex_trader

# Build production image
build:
	podman build \
		--layers \
		-f docker/Dockerfile \
		-t $(IMAGE):$(VERSION) \
		-t $(IMAGE):$(COMMIT) \
		-t $(IMAGE):$(DATE) \
		-t $(IMAGE):latest \
		--label org.opencontainers.image.version=$(VERSION) \
		--label org.opencontainers.image.revision=$(COMMIT) \
		--label org.opencontainers.image.created=$(shell date -u +%Y-%m-%dT%H:%M:%SZ) \
		.
	@echo "Built image: $(IMAGE):$(VERSION)"

# Build development image
build-dev:
	podman build \
		-f docker/Dockerfile.dev \
		-t $(IMAGE):dev \
		.
	@echo "Built dev image: $(IMAGE):dev"

# Tag image for registry
tag:
	podman tag $(IMAGE):$(VERSION) $(REGISTRY)/$(IMAGE):$(VERSION)
	podman tag $(IMAGE):$(VERSION) $(REGISTRY)/$(IMAGE):latest
	@echo "Tagged for registry: $(REGISTRY)/$(IMAGE):$(VERSION)"

# Run smoke tests
test:
	@echo "Running smoke tests..."
	@podman images | grep $(IMAGE)
	@echo "\n✓ Image exists"

	@podman run --rm \
		-e SECRET_KEY=test-secret-key \
		-e FIELD_ENCRYPTION_KEY=test-encryption-key \
		$(IMAGE):$(VERSION) \
		python manage.py check
	@echo "✓ Django check passed"

	@echo "\n✓ All tests passed"

# Push to registry
push: tag
	podman push $(REGISTRY)/$(IMAGE):$(VERSION)
	podman push $(REGISTRY)/$(IMAGE):latest
	@echo "Pushed to registry: $(REGISTRY)/$(IMAGE):$(VERSION)"

# Clean up dangling images
clean:
	podman image prune -f
	@echo "Cleaned up dangling images"

# Full workflow: build, test, push
release: build test push
	@echo "Release complete: $(VERSION)"
```

### Usage

**Build**:
```bash
make build
```

**Build and Test**:
```bash
make build test
```

**Full Release** (build, test, push):
```bash
make release
```

**Development Build**:
```bash
make build-dev
```

**Clean Up**:
```bash
make clean
```

---

## Multi-Architecture Builds

### Build for Multiple Platforms

**Important**: Podman requires separate builds per architecture (unlike Docker Buildx which can build multiple platforms in one command).

**Step 1: Create Manifest**:
```bash
podman manifest create senex_trader:latest
```

**Step 2: Build for AMD64**:
```bash
podman build \
  --platform linux/amd64 \
  --manifest senex_trader:latest \
  .
```

**Step 3: Build for ARM64**:
```bash
podman build \
  --platform linux/arm64 \
  --manifest senex_trader:latest \
  .
```

**Step 4: Verify Manifest**:
```bash
podman manifest inspect senex_trader:latest
```

**Expected Output**:
```json
{
  "manifests": [
    {
      "platform": {
        "architecture": "amd64",
        "os": "linux"
      }
    },
    {
      "platform": {
        "architecture": "arm64",
        "os": "linux"
      }
    }
  ]
}
```

**Step 5: Push Multi-Arch Manifest**:
```bash
podman manifest push senex_trader:latest docker://myregistry.com/senex_trader:latest
```

---

## Registry Operations

### Login to Registry

**Docker Hub**:
```bash
podman login docker.io
# Username: yourusername
# Password: ****
```

**Private Registry**:
```bash
podman login myregistry.com
# Username: admin
# Password: ****
```

**GitHub Container Registry**:
```bash
podman login ghcr.io
# Username: yourusername
# Password: <github-personal-access-token>
```

### Pushing Images

**Single Tag**:
```bash
podman push myregistry.com/senex_trader:1.2.3
```

**Multiple Tags** (script):
```bash
#!/bin/bash
VERSION="1.2.3"
REGISTRY="myregistry.com"
IMAGE="senex_trader"

tags=("$VERSION" "latest" "$(git rev-parse --short HEAD)")

for tag in "${tags[@]}"; do
    echo "Pushing $REGISTRY/$IMAGE:$tag"
    podman push "$REGISTRY/$IMAGE:$tag"
done
```

### Pulling Images

**From Registry**:
```bash
podman pull myregistry.com/senex_trader:1.2.3
```

**Verify Signature** (if using signed images):
```bash
podman pull --signature-policy /etc/containers/policy.json \
  myregistry.com/senex_trader:1.2.3
```

---

## CI/CD Integration

### GitHub Actions

**File**: `.github/workflows/build-and-push.yml`

```yaml
name: Build and Push Docker Image

on:
  push:
    branches:
      - main
      - develop
    tags:
      - 'v*'
  pull_request:
    branches:
      - main

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Podman
        run: |
          sudo apt-get update
          sudo apt-get install -y podman

      - name: Log in to registry
        run: |
          echo "${{ secrets.GITHUB_TOKEN }}" | podman login ghcr.io -u ${{ github.actor }} --password-stdin

      - name: Extract metadata
        id: meta
        run: |
          VERSION=$(git describe --tags --always --dirty)
          COMMIT=$(git rev-parse --short HEAD)
          echo "version=$VERSION" >> $GITHUB_OUTPUT
          echo "commit=$COMMIT" >> $GITHUB_OUTPUT

      - name: Build image
        run: |
          podman build \
            --layers \
            -f docker/Dockerfile \
            -t ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ steps.meta.outputs.version }} \
            -t ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest \
            --label org.opencontainers.image.version=${{ steps.meta.outputs.version }} \
            --label org.opencontainers.image.revision=${{ steps.meta.outputs.commit }} \
            .

      - name: Run tests
        run: |
          podman run --rm \
            -e SECRET_KEY=test-secret-key \
            -e FIELD_ENCRYPTION_KEY=test-encryption-key \
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ steps.meta.outputs.version }} \
            python manage.py check

      - name: Push image
        if: github.event_name != 'pull_request'
        run: |
          podman push ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ steps.meta.outputs.version }}
          podman push ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
```

### GitLab CI

**File**: `.gitlab-ci.yml`

```yaml
stages:
  - build
  - test
  - push

variables:
  REGISTRY: registry.gitlab.com
  IMAGE: $REGISTRY/$CI_PROJECT_PATH

build:
  stage: build
  image: quay.io/podman/stable
  script:
    - podman build -t $IMAGE:$CI_COMMIT_SHORT_SHA -f docker/Dockerfile .
    - podman save $IMAGE:$CI_COMMIT_SHORT_SHA -o image.tar
  artifacts:
    paths:
      - image.tar
    expire_in: 1 hour

test:
  stage: test
  image: quay.io/podman/stable
  script:
    - podman load -i image.tar
    - podman run --rm -e SECRET_KEY=test -e FIELD_ENCRYPTION_KEY=test $IMAGE:$CI_COMMIT_SHORT_SHA python manage.py check
  dependencies:
    - build

push:
  stage: push
  image: quay.io/podman/stable
  script:
    - podman load -i image.tar
    - echo "$CI_REGISTRY_PASSWORD" | podman login -u $CI_REGISTRY_USER --password-stdin $REGISTRY
    - podman tag $IMAGE:$CI_COMMIT_SHORT_SHA $IMAGE:latest
    - podman push $IMAGE:$CI_COMMIT_SHORT_SHA
    - podman push $IMAGE:latest
  dependencies:
    - build
  only:
    - main
    - tags
```

---

## Image Security Scanning

### Scan for Vulnerabilities

**Using Trivy**:
```bash
# Install Trivy
sudo apt-get install wget apt-transport-https gnupg lsb-release
wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
echo "deb https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee -a /etc/apt/sources.list.d/trivy.list
sudo apt-get update
sudo apt-get install trivy

# Scan image
trivy image senex_trader:latest
```

**Using Podman Scout** (if available):
```bash
podman scout cves senex_trader:latest
```

### Fix Vulnerabilities

**Update Base Image**:
```dockerfile
# Old
FROM python:3.12-slim-bookworm

# New (with latest security patches)
FROM python:3.12-slim-bookworm@sha256:latest-digest
```

**Update Dependencies**:
```bash
# Update requirements.txt to latest patched versions
pip list --outdated
pip install --upgrade package-name
```

---

## Image Optimization

### Size Reduction Techniques

#### 1. Check Current Size

```bash
podman images senex_trader:latest --format "{{.Size}}"
# 650 MB
```

#### 2. Analyze Layers

```bash
podman history senex_trader:latest
```

**Output**:
```
IMAGE          CREATED        CREATED BY                                      SIZE
abc123         2 minutes ago  CMD ["web"]                                     0B
def456         2 minutes ago  HEALTHCHECK                                     0B
ghi789         2 minutes ago  COPY . /app/                                    10MB
jkl012         3 minutes ago  RUN pip install -r requirements.txt             300MB
mno345         5 minutes ago  RUN apt-get install ...                         50MB
pqr678         5 minutes ago  FROM python:3.12-slim-bookworm                  120MB
```

#### 3. Identify Large Layers

**Use dive** (interactive layer explorer):
```bash
# Install dive
wget https://github.com/wagoodman/dive/releases/download/v0.10.0/dive_0.10.0_linux_amd64.deb
sudo dpkg -i dive_0.10.0_linux_amd64.deb

# Analyze image
dive senex_trader:latest
```

#### 4. Optimize

**Strategies**:
- Remove unnecessary packages
- Clear apt cache in same RUN layer
- Use .dockerignore to exclude large files
- Compress static files
- Use multi-stage build (exclude build tools)

**Example Optimization**:
```dockerfile
# Before (300 MB layer)
RUN apt-get update && \
    apt-get install -y gcc build-essential libpq-dev

# After (50 MB layer)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential libpq-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

---

## Version Control Integration

### Git Tags for Releases

**Create Tag**:
```bash
git tag -a v1.2.3 -m "Release version 1.2.3"
git push origin v1.2.3
```

**Build from Tag**:
```bash
# Checkout tag
git checkout v1.2.3

# Build with tag version
VERSION=$(git describe --tags)
podman build -t senex_trader:$VERSION .
```

### Automated Versioning

**Script**: `scripts/build.sh`

```bash
#!/bin/bash
set -e

# Get version from git
VERSION=$(git describe --tags --always --dirty)
COMMIT=$(git rev-parse --short HEAD)
DATE=$(date +%Y%m%d)

echo "Building Senex Trader $VERSION"

# Build image
podman build \
  --layers \
  -f docker/Dockerfile \
  -t senex_trader:$VERSION \
  -t senex_trader:$COMMIT \
  -t senex_trader:latest \
  --label org.opencontainers.image.version=$VERSION \
  --label org.opencontainers.image.revision=$COMMIT \
  --label org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  .

echo "Build complete: senex_trader:$VERSION"
```

**Usage**:
```bash
chmod +x scripts/build.sh
./scripts/build.sh
```

---

## Rollback Strategy

### Image Digest Pinning

**Get Digest**:
```bash
podman images --digests senex_trader
# REPOSITORY    TAG     DIGEST                                                                   IMAGE ID
# senex_trader  1.2.3   sha256:abc123...                                                        def456
```

**Pull by Digest** (immutable):
```bash
podman pull myregistry.com/senex_trader@sha256:abc123...
```

**Benefit**: Exact image, immune to tag updates

### Rollback Procedure

**Production Rollback**:
```bash
# Current version
podman ps | grep senex_web
# senex_web  myregistry.com/senex_trader:1.2.3

# Rollback to previous version
podman-compose down
podman pull myregistry.com/senex_trader:1.2.2
podman tag myregistry.com/senex_trader:1.2.2 senex_trader:latest
podman-compose up -d

# Verify
podman ps | grep senex_web
# senex_web  myregistry.com/senex_trader:1.2.2
```

---

## Summary

**Build Workflow provides**:

- ✅ **Automated Builds**: Makefile and scripts for consistent builds
- ✅ **Semantic Versioning**: Clear version tagging strategy
- ✅ **Multi-Architecture**: x86_64 + ARM64 support
- ✅ **CI/CD Integration**: GitHub Actions and GitLab CI examples
- ✅ **Security Scanning**: Vulnerability detection
- ✅ **Image Optimization**: Size reduction techniques
- ✅ **Registry Management**: Push/pull workflows
- ✅ **Rollback Strategy**: Version pinning and recovery

**Quick Start**:
```bash
# Build locally
make build

# Test
make test

# Push to registry
make push

# Full release
make release
```

**Next Steps**: See `initialization-checklist.md` for deployment procedures and `implementation-requirements.md` for required code changes.
