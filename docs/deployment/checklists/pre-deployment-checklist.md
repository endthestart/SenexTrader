# Pre-Deployment Checklist for Senex Trader

## Infrastructure

- [ ] **Servers provisioned** per infrastructure requirements
  - [ ] Correct CPU/RAM/storage specs for target phase
  - [ ] Operating system installed (Ubuntu 24.04 LTS or Rocky Linux 9)
  - [ ] Root access via SSH key authentication
  
- [ ] **Network configuration**
  - [ ] Firewall configured (ports 22, 80, 443 open)
  - [ ] DNS records created (A record for your-domain.com)
  - [ ] DNS TTL set to 300 seconds (5 minutes)
  - [ ] Outbound HTTPS (443) allowed for TastyTrade API

- [ ] **Domain and SSL**
  - [ ] Domain ownership verified
  - [ ] DNS propagation complete (`dig your-domain.com`)
  - [ ] Ready for Let's Encrypt certificate generation

## Software Prerequisites

- [ ] **System packages**
  - [ ] OS updated (`apt update && apt upgrade`)
  - [ ] Podman 4.4+ installed
  - [ ] Python 3.11+ installed
  - [ ] PostgreSQL client tools installed
  
- [ ] **Security**
  - [ ] Unattended upgrades enabled
  - [ ] Fail2ban configured
  - [ ] SELinux (RHEL/Rocky) or AppArmor (Ubuntu) enabled
  
- [ ] **Service user**
  - [ ] User `senex` created
  - [ ] Systemd lingering enabled for `senex`
  - [ ] Subuid/subgid configured for rootless containers

## Ansible Configuration

- [ ] **Control machine**
  - [ ] Ansible 2.15+ installed
  - [ ] Required collections installed (`ansible-galaxy collection install -r requirements.yml`)
  - [ ] SSH access to target servers configured
  
- [ ] **Inventory**
  - [ ] Production inventory created (`inventory/production/hosts.yml`)
  - [ ] Group variables configured (`inventory/production/group_vars/all.yml`)
  - [ ] SSH connectivity tested (`ansible all -m ping`)

## Secrets and Credentials

- [ ] **Encryption keys generated**
  - [ ] Django SECRET_KEY
  - [ ] FIELD_ENCRYPTION_KEY (Fernet)
  - [ ] Database password (strong, 24+ characters)
  - [ ] Redis password (strong, 32+ characters)
  
- [ ] **Ansible Vault**
  - [ ] Vault password file created (`~/.vault_pass_production`)
  - [ ] Vault file created (`inventory/production/group_vars/vault.yml`)
  - [ ] All sensitive credentials encrypted in vault
  - [ ] Vault password file secured (chmod 600)
  - [ ] Vault password file added to .gitignore
  
- [ ] **TastyTrade credentials**
  - [ ] OAuth client ID obtained
  - [ ] OAuth client secret obtained
  - [ ] Credentials tested in staging/sandbox environment
  
- [ ] **Email configuration (optional)**
  - [ ] SMTP server configured
  - [ ] App-specific password generated (if using Gmail)
  - [ ] Test email sent successfully

## Application Build

- [ ] **Docker image**
  - [ ] Django application image built
  - [ ] Image pushed to container registry
  - [ ] Registry credentials configured in Ansible
  - [ ] Image pull tested on target server
  
- [ ] **Configuration files**
  - [ ] Environment variables template reviewed
  - [ ] Quadlet files prepared for all services
  - [ ] Nginx configuration reviewed
  - [ ] Redis configuration reviewed

## Backup Configuration

- [ ] **Backup storage**
  - [ ] S3-compatible storage account created
  - [ ] Access credentials generated
  - [ ] Credentials added to Ansible Vault
  - [ ] Backup bucket created
  
- [ ] **Backup scripts**
  - [ ] PostgreSQL backup script deployed
  - [ ] Redis backup script deployed
  - [ ] Backup scripts tested (dry run)
  - [ ] Cron jobs configured for automated backups

## Monitoring Setup

- [ ] **External monitoring**
  - [ ] UptimeRobot or equivalent configured
  - [ ] Health check endpoint monitored
  - [ ] Alert contacts configured (email/Slack)
  
- [ ] **Internal monitoring (Phase 2+)**
  - [ ] Prometheus server provisioned
  - [ ] Grafana server provisioned
  - [ ] Alert rules configured

## Security Validation

- [ ] **Secrets verification**
  - [ ] No secrets in plain text files
  - [ ] No secrets in git history
  - [ ] Environment files not committed to git (`.env` in `.gitignore`)
  
- [ ] **Container security**
  - [ ] Rootless Podman confirmed (user namespace active)
  - [ ] SELinux labels on volumes configured (`:Z` or `:z`)
  - [ ] No containers running as root
  
- [ ] **Network security**
  - [ ] Only required ports exposed
  - [ ] Internal services not accessible from internet
  - [ ] Podman network created for service isolation

## Final Checks

- [ ] **Documentation reviewed**
  - [ ] 00-OVERVIEW.md understood
  - [ ] 01-INFRASTRUCTURE-REQUIREMENTS.md verified
  - [ ] 02-ANSIBLE-STRUCTURE.md reviewed
  - [ ] 03-SECRETS-MANAGEMENT.md procedures understood
  
- [ ] **Rollback plan**
  - [ ] Previous backup exists (if updating)
  - [ ] Rollback procedure documented
  - [ ] Downtime window communicated to users (if applicable)
  
- [ ] **Team readiness**
  - [ ] Deployment team identified
  - [ ] Communication channels established
  - [ ] On-call support scheduled for go-live window

## Deployment Approval

- [ ] **Technical approval**
  - [ ] Lead developer signed off
  - [ ] DevOps engineer signed off
  
- [ ] **Business approval**
  - [ ] Stakeholders notified
  - [ ] Go-live window approved
  - [ ] Maintenance page prepared (if needed)

---

**Checklist completed by**: _______________  
**Date**: _______________  
**Ready for deployment**: ☐ Yes  ☐ No  

**Notes/Issues**:
