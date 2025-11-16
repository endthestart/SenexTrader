# Go-Live Checklist for Senex Trader

## T-1 Hour: Final Preparation

- [ ] **Verify pre-deployment checklist** completed
- [ ] **Team assembled** (developer, devops, stakeholder on call)
- [ ] **Communication sent** to stakeholders
- [ ] **Maintenance page** activated (if applicable)
- [ ] **Final backup** completed of any existing system

## T-0: Deployment Execution

### Step 1: Deploy Infrastructure (15 minutes)

- [ ] Run Ansible playbook:
  ```bash
  ansible-playbook -i inventory/production/hosts.yml site.yml \
    --vault-password-file ~/.vault_pass_production
  ```
- [ ] Monitor playbook execution for errors
- [ ] Verify all tasks completed successfully

### Step 2: Verify Services (10 minutes)

- [ ] Check container status:
  ```bash
  podman ps --format "table {{.Names}}\t{{.Status}}"
  ```
- [ ] Verify all services running:
  - [ ] PostgreSQL
  - [ ] Redis
  - [ ] Django/Daphne
  - [ ] Celery Worker
  - [ ] Celery Beat
  - [ ] Nginx

### Step 3: Database Setup (5 minutes)

- [ ] Verify migrations applied:
  ```bash
  podman exec django python manage.py showmigrations
  ```
- [ ] Create superuser:
  ```bash
  podman exec -it django python manage.py createsuperuser
  ```

### Step 4: Health Checks (10 minutes)

- [ ] Run health check script:
  ```bash
  /opt/scripts/health-check.sh
  ```
- [ ] Verify health endpoint:
  ```bash
  curl https://your-domain.com/health/
  ```
  Expected: `{"status": "healthy", "checks": {"database": "ok", "cache": "ok", "celery_broker": "ok"}}`

- [ ] Check Django admin accessible:
  ```bash
  curl -I https://your-domain.com/admin/
  ```
  Expected: HTTP 200 or 302

### Step 5: SSL/TLS Validation (5 minutes)

- [ ] Verify SSL certificate:
  ```bash
  echo | openssl s_client -servername your-domain.com -connect your-domain.com:443 2>/dev/null | openssl x509 -noout -dates
  ```
- [ ] Check HSTS header:
  ```bash
  curl -I https://your-domain.com | grep -i strict-transport-security
  ```
- [ ] Verify HTTP→HTTPS redirect:
  ```bash
  curl -I http://your-domain.com
  ```
  Expected: 301 redirect to HTTPS

### Step 6: Functional Testing (15 minutes)

- [ ] **User login** tested
- [ ] **TastyTrade OAuth** connection successful
- [ ] **Market data** fetched successfully
- [ ] **WebSocket connection** established
  - Open browser console
  - Test: `new WebSocket('wss://your-domain.com/ws/streaming/')`
  - Verify: Connection established without errors

- [ ] **Celery task execution** verified:
  ```bash
  podman exec django celery -A senextrader inspect active
  ```

- [ ] **Scheduled tasks** visible in admin:
  - Login to `/admin/`
  - Navigate to Periodic Tasks
  - Verify all expected tasks present

### Step 7: Monitoring Setup (5 minutes)

- [ ] **Grafana dashboards** accessible (if Phase 2+)
- [ ] **Prometheus targets** up
- [ ] **UptimeRobot** monitoring active
- [ ] **Alert test** sent and received

## T+1 Hour: Post-Deployment Validation

### Operational Checks

- [ ] **Application logs** reviewed for errors:
  ```bash
  journalctl --user -u django.service -n 100 --no-pager
  journalctl --user -u celery-worker.service -n 100 --no-pager
  ```

- [ ] **Database connections** stable:
  ```bash
  podman exec postgres psql -U senex_user -d senextrader -c \
    "SELECT count(*) FROM pg_stat_activity WHERE datname='senextrader';"
  ```

- [ ] **Redis memory** within limits:
  ```bash
  podman exec redis redis-cli INFO memory | grep used_memory_human
  ```

- [ ] **Celery queue** processing:
  ```bash
  podman exec django celery -A senextrader inspect stats
  ```

### Performance Checks

- [ ] **Response time** acceptable:
  ```bash
  curl -w "@curl-format.txt" -o /dev/null -s https://your-domain.com/
  # Format file: time_total: %{time_total}\n
  ```
  Expected: <500ms for homepage

- [ ] **Database query performance** acceptable
  - Check slow query log
  - Verify no queries >1s

- [ ] **No memory leaks** detected:
  ```bash
  podman stats --no-stream
  ```

### Security Validation

- [ ] **HTTPS enforced** (no HTTP access except .well-known)
- [ ] **Rate limiting** functional (test by exceeding limits)
- [ ] **CORS headers** correct (if API exposed)
- [ ] **WebSocket origin** validation working
- [ ] **Redis authentication** required:
  ```bash
  podman exec redis redis-cli PING
  # Expected: (error) NOAUTH Authentication required
  ```

## T+4 Hours: Extended Monitoring

- [ ] **No error spikes** in logs
- [ ] **Celery tasks** completing successfully
- [ ] **External monitoring** shows 100% uptime
- [ ] **User feedback** collected (if applicable)
- [ ] **Resource usage** stable (CPU, memory, disk)

## T+24 Hours: Post-Launch Review

- [ ] **Backup verification**:
  ```bash
  ls -lh /var/backups/postgresql/
  ```
  Expected: Backup file created in last 24 hours

- [ ] **Performance metrics** reviewed:
  - Average response time
  - Error rate
  - Database query performance
  - Celery task throughput

- [ ] **Security scan** (optional):
  ```bash
  nmap -sV -p 80,443 your-domain.com
  # Verify only expected ports open
  ```

- [ ] **Retrospective** scheduled with team

## Rollback Procedure (If Needed)

If critical issues arise:

1. **Stop new deployments**:
   ```bash
   # Mark deployment as failed
   echo "DEPLOYMENT FAILED - ROLLBACK IN PROGRESS" > /tmp/deployment_status
   ```

2. **Activate maintenance page** (if prepared)

3. **Restore from backup** (if database changes made):
   ```bash
   /opt/scripts/restore-postgresql.sh /var/backups/postgresql/senextrader_LATEST.backup.gz
   ```

4. **Revert code** (if application issues):
   ```bash
   # Pull previous image version
   podman pull registry.example.com/senex-trader:v1.0.0
   # Update Quadlet files to use previous version
   # Restart services
   systemctl --user restart django.service celery-worker.service
   ```

5. **Notify stakeholders** of rollback

6. **Document issues** for post-mortem

## Sign-Off

### Deployment Completion

- [ ] **All checklist items** completed
- [ ] **No critical issues** identified
- [ ] **Monitoring** active and alerting
- [ ] **Team dismissed** from on-call status

**Deployment completed by**: _______________  
**Date/Time**: _______________  
**Status**: ☐ Successful  ☐ Successful with minor issues  ☐ Rolled back  

**Issues encountered**:

**Lessons learned**:
