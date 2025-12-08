#!/bin/bash
# Comprehensive health check for Senex Trader
# Usage: ./health-check.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_status=0

echo "=== Senex Trader Health Check ==="
echo ""

# Check container status
echo "1. Container Status:"
for container in postgres redis django celery-worker celery-beat; do
    if podman ps --format "{{.Names}}" | grep -q "^${container}$"; then
        echo -e "  ${GREEN}[OK]${NC} $container is running"
    else
        echo -e "  ${RED}[FAIL]${NC} $container is NOT running"
        check_status=1
    fi
done
echo ""

# Check PostgreSQL
echo "2. PostgreSQL:"
if podman exec postgres pg_isready -U senex_user &> /dev/null; then
    echo -e "  ${GREEN}[OK]${NC} PostgreSQL is accepting connections"
else
    echo -e "  ${RED}[FAIL]${NC} PostgreSQL is NOT accepting connections"
    check_status=1
fi
echo ""

# Check Redis
echo "3. Redis:"
if podman exec redis redis-cli -a "${REDIS_PASSWORD:-}" ping &> /dev/null; then
    echo -e "  ${GREEN}[OK]${NC} Redis is responding"
else
    echo -e "  ${RED}[FAIL]${NC} Redis is NOT responding"
    check_status=1
fi
echo ""

# Check Django health endpoint
echo "4. Django Application:"
if curl -sf http://localhost:8000/health/ > /dev/null; then
    echo -e "  ${GREEN}[OK]${NC} Django health endpoint is OK"
    curl -s http://localhost:8000/health/ | jq '.' 2>/dev/null || echo "  (jq not installed for JSON formatting)"
else
    echo -e "  ${RED}[FAIL]${NC} Django health endpoint FAILED"
    check_status=1
fi
echo ""

# Check Celery workers
echo "5. Celery Workers:"
ACTIVE_WORKERS=$(podman exec django celery -A senextrader inspect active 2>/dev/null | grep -c "celery@" || echo "0")
if [ "$ACTIVE_WORKERS" -gt 0 ]; then
    echo -e "  ${GREEN}[OK]${NC} Celery workers active: $ACTIVE_WORKERS"
else
    echo -e "  ${YELLOW}⚠${NC} No Celery workers detected"
    check_status=1
fi
echo ""

# Check disk space
echo "6. Disk Space:"
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 80 ]; then
    echo -e "  ${GREEN}[OK]${NC} Disk usage: ${DISK_USAGE}%"
elif [ "$DISK_USAGE" -lt 90 ]; then
    echo -e "  ${YELLOW}⚠${NC} Disk usage: ${DISK_USAGE}% (warning)"
else
    echo -e "  ${RED}[FAIL]${NC} Disk usage: ${DISK_USAGE}% (critical)"
    check_status=1
fi
echo ""

# Check memory
echo "7. Memory Usage:"
MEMORY_USAGE=$(free | awk 'NR==2 {printf "%.0f", $3/$2*100}')
if [ "$MEMORY_USAGE" -lt 80 ]; then
    echo -e "  ${GREEN}[OK]${NC} Memory usage: ${MEMORY_USAGE}%"
elif [ "$MEMORY_USAGE" -lt 90 ]; then
    echo -e "  ${YELLOW}⚠${NC} Memory usage: ${MEMORY_USAGE}% (warning)"
else
    echo -e "  ${RED}[FAIL]${NC} Memory usage: ${MEMORY_USAGE}% (critical)"
    check_status=1
fi
echo ""

# Check SSL certificate expiration (if HTTPS enabled)
echo "8. SSL Certificate:"
if command -v openssl &> /dev/null && [ -f "/etc/letsencrypt/live/senextrader.com/cert.pem" ]; then
    CERT_EXPIRY=$(openssl x509 -in /etc/letsencrypt/live/senextrader.com/cert.pem -noout -enddate | cut -d= -f2)
    EXPIRY_EPOCH=$(date -d "$CERT_EXPIRY" +%s)
    NOW_EPOCH=$(date +%s)
    DAYS_UNTIL_EXPIRY=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))
    
    if [ "$DAYS_UNTIL_EXPIRY" -gt 30 ]; then
        echo -e "  ${GREEN}[OK]${NC} SSL certificate expires in ${DAYS_UNTIL_EXPIRY} days"
    elif [ "$DAYS_UNTIL_EXPIRY" -gt 7 ]; then
        echo -e "  ${YELLOW}⚠${NC} SSL certificate expires in ${DAYS_UNTIL_EXPIRY} days"
    else
        echo -e "  ${RED}[FAIL]${NC} SSL certificate expires in ${DAYS_UNTIL_EXPIRY} days (critical)"
        check_status=1
    fi
else
    echo -e "  ${YELLOW}⚠${NC} SSL certificate not found or openssl not installed"
fi
echo ""

# Summary
echo "=== Health Check Summary ==="
if [ $check_status -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${NC}"
    exit 0
else
    echo -e "${RED}Some checks failed. Please investigate.${NC}"
    exit 1
fi
