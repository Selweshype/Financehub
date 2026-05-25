.PHONY: dev build up down logs shell test lint backup init-db help

COMPOSE = docker compose
APP = $(COMPOSE) exec app

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

build: ## Build all Docker images
	$(COMPOSE) build

up: ## Start all services
	$(COMPOSE) up -d

down: ## Stop all services
	$(COMPOSE) down

dev: ## Start services and follow logs
	$(COMPOSE) up

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

logs-app: ## Follow app logs only
	$(COMPOSE) logs -f app

shell: ## Open a shell in the app container
	$(APP) /bin/bash

init-db: ## Run Alembic migrations and seed categories/rules
	$(APP) /bin/bash /app/scripts/init_db.sh

migrate: ## Run Alembic migrations only
	$(APP) python -m alembic upgrade head

test: ## Run test suite
	$(APP) python -m pytest tests/ -v

lint: ## Run ruff linter + bandit security scanner
	$(APP) python -m ruff check app/
	$(APP) python -m bandit -r app/ -ll

backup: ## Run Restic backup (runs the backup container)
	$(COMPOSE) run --rm backup

sync: ## Trigger a manual transaction sync
	$(APP) python -c "from app.services.sync_service import run_full_sync; import asyncio; asyncio.run(run_full_sync())"

ps: ## Show running containers
	$(COMPOSE) ps

download-static: ## Download htmx 2.0.4 and Alpine.js 3.14 into static/js/
	@mkdir -p static/js
	@echo "Downloading htmx 2.0.4..."
	curl -fsSL https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js -o static/js/htmx.min.js
	@echo "Downloading Alpine.js 3.14.1..."
	curl -fsSL https://unpkg.com/alpinejs@3.14.1/dist/cdn.min.js -o static/js/alpine.min.js
	@echo "Done. Static assets saved to static/js/"
