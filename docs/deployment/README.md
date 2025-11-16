# Deployment Documentation

This folder contains operational guides and documentation for deploying and maintaining Senex Trader in production environments.

## Contents Overview

### Infrastructure Setup
- Ansible playbooks and configurations
- Podman/Quadlet container orchestration
- UFW firewall rules
- Systemd service configurations
- PostgreSQL backup automation

### Environment Management
- Production vs staging configuration differences
- Environment variable management
- Secret management
- DNS and network configuration

### Operational Procedures
- Deployment workflows
- Backup and restore procedures
- Service monitoring
- Troubleshooting guides

## Key Files

- `README.md` - This file
- `ansible/` - Infrastructure automation
  - `deploy.yml` - Main deployment playbook
  - `inventory/hosts.yml` - Server inventory
  - `templates/` - Service templates (Quadlet, backup scripts, etc.)
- Environment-specific documentation

## File Count

16 operational guide files

## Usage

Refer to these documents when:
- Deploying to new environments
- Updating production infrastructure
- Configuring backup systems
- Troubleshooting deployment issues
- Understanding environment differences

## Related Documentation

- Main project: `/path/to/senex_trader/`
- Docker documentation: `../docker/`
- Architecture documentation: `../architecture/`
