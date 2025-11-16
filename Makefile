# Senex Trader Makefile
# Provides simple deployment commands for monorepo structure

# Colors for output
CYAN := \033[0;36m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m # No Color

.PHONY: help setup check-config deploy-staging deploy-production build

help:
	@printf "$(CYAN)Senex Trader Deployment Commands$(NC)\n"
	@printf "\n"
	@printf "$(GREEN)Available commands:$(NC)\n"
	@printf "  make setup             - Validate configuration setup\n"
	@printf "  make check-config      - Display current configuration\n"
	@printf "  make deploy-staging    - Deploy to staging environment\n"
	@printf "  make deploy-production - Deploy to production environment\n"
	@printf "  make build TAG=vX.X.X  - Build container image with specified tag\n"
	@printf "\n"
	@printf "$(YELLOW)Requirements:$(NC)\n"
	@printf "  - Inventory: config/ansible/inventory/hosts.yml\n"
	@printf "  - Build config: .senex_trader.json (copy from .senex_trader.json.example)\n"

setup:
	@printf "$(CYAN)Validating Senex Trader Configuration...$(NC)\n"
	@test -f "config/ansible/inventory/hosts.yml" || (printf "$(YELLOW)ERROR: Ansible inventory not found at config/ansible/inventory/hosts.yml$(NC)\n" && exit 1)
	@test -f ".senex_trader.json" || (printf "$(YELLOW)ERROR: .senex_trader.json not found. Copy from .senex_trader.json.example$(NC)\n" && exit 1)
	@printf "$(GREEN)✓ Configuration validated$(NC)\n"
	@printf "$(GREEN)✓ Inventory: config/ansible/inventory/hosts.yml$(NC)\n"
	@printf "$(GREEN)✓ Build config: .senex_trader.json$(NC)\n"

check-config: setup
	@printf "$(CYAN)Current Configuration:$(NC)\n"
	@printf "  Inventory:   config/ansible/inventory/hosts.yml\n"
	@printf "  Build config: .senex_trader.json\n"
	@printf "\n"
	@printf "$(CYAN)Available Hosts:$(NC)\n"
	@cd deployment/ansible && ansible-inventory -i ../../config/ansible/inventory --list -y | head -20

deploy-staging: setup
	@printf "$(CYAN)Deploying to Staging...$(NC)\n"
	cd deployment/ansible && ansible-playbook deploy.yml --limit staging

deploy-production: setup
	@printf "$(YELLOW)⚠️  Deploying to PRODUCTION...$(NC)\n"
	@printf "Press Ctrl+C to cancel, or wait 5 seconds to continue...\n"
	@sleep 5
	@printf "$(CYAN)Starting production deployment...$(NC)\n"
	cd deployment/ansible && ansible-playbook deploy.yml --limit production

build: setup
	@test -n "$(TAG)" || (printf "$(YELLOW)ERROR: TAG required. Usage: make build TAG=v1.2.3$(NC)\n" && exit 1)
	@printf "$(CYAN)Building container image $(TAG)...$(NC)\n"
	./build.py --tag $(TAG)
	@printf "$(GREEN)✓ Build complete: $(TAG)$(NC)\n"
