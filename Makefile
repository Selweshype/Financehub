.PHONY: dev build up down logs logs-app shell test lint backup help browser-test \
        migrate sync ps download-static check-static venv

COMPOSE = docker compose
APP = $(COMPOSE) exec app

# Tests and linters run on the HOST, not in the container. The runtime image is
# deliberately slim — it contains no test code, no dev dependencies and no
# linters — so `docker compose exec app pytest tests/` could never have worked.
VENV = backend/.venv
PY   = $(VENV)/bin/python

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

build: check-static ## Build all Docker images (verifies vendored JS first)
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

# NOTE: there is deliberately no `init-db` target. It used to run
# /app/scripts/init_db.sh, which never existed, and it was redundant anyway:
# migration 0001 seeds the categories and Dutch merchant rules, and
# entrypoint.sh runs `alembic upgrade head` on every container start.

migrate: ## Run Alembic migrations only
	$(APP) python -m alembic upgrade head

venv: ## Create the host dev virtualenv used by `make test` and `make lint`
	cd backend && uv sync
	@echo "Dev virtualenv ready at $(VENV)"

test: ## Run test suite (host)
	PYTHONPATH=backend $(PY) -m pytest tests/ -v

lint: ## Run ruff linter + bandit security scanner (host)
	cd backend && .venv/bin/ruff check app/ ../tests/
	cd backend && .venv/bin/bandit -r app/ -ll

backup: ## Run Restic backup (runs the backup container)
	$(COMPOSE) run --rm backup

sync: ## Trigger a manual transaction sync
	$(APP) python -c "import asyncio; from app.services.sync_service import sync_all; asyncio.run(sync_all())"

ps: ## Show running containers
	$(COMPOSE) ps

# Vendored frontend libraries. The CSP allows no external script hosts, so these
# are committed to the repo rather than loaded from a CDN. Fetched from the npm
# registry (unpkg is not reachable from every environment) and checksum-verified,
# because a silently-truncated or substituted download would be executed by every
# page in the app.
HTMX_VERSION    = 2.0.4
HTMX_SHA256     = e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447
ALPINE_VERSION  = 3.14.1
ALPINE_SHA256   = 358d9afbb1ab5befa2f48061a30776e5bcd7707f410a606ba985f98bc3b1c034

download-static: ## Download + verify htmx and Alpine.js into static/js/
	@mkdir -p static/js
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	echo "Downloading htmx $(HTMX_VERSION)..." && \
	curl -fsSL "https://registry.npmjs.org/htmx.org/-/htmx.org-$(HTMX_VERSION).tgz" -o "$$tmp/htmx.tgz" && \
	tar xzf "$$tmp/htmx.tgz" -C "$$tmp" package/dist/htmx.min.js && \
	echo "$(HTMX_SHA256)  $$tmp/package/dist/htmx.min.js" | sha256sum -c - && \
	cp "$$tmp/package/dist/htmx.min.js" static/js/htmx.min.js && \
	rm -rf "$$tmp/package" && \
	echo "Downloading Alpine.js $(ALPINE_VERSION)..." && \
	curl -fsSL "https://registry.npmjs.org/alpinejs/-/alpinejs-$(ALPINE_VERSION).tgz" -o "$$tmp/alpine.tgz" && \
	tar xzf "$$tmp/alpine.tgz" -C "$$tmp" package/dist/cdn.min.js && \
	echo "$(ALPINE_SHA256)  $$tmp/package/dist/cdn.min.js" | sha256sum -c - && \
	cp "$$tmp/package/dist/cdn.min.js" static/js/alpine.min.js
	@echo "Static assets verified and saved to static/js/"

check-static: ## Fail if static/js holds placeholder stubs instead of the real libraries
	@echo "$(HTMX_SHA256)  static/js/htmx.min.js" | sha256sum -c - >/dev/null 2>&1 || \
		{ echo "ERROR: static/js/htmx.min.js is missing or not the expected build."; \
		  echo "       Run 'make download-static'."; exit 1; }
	@echo "$(ALPINE_SHA256)  static/js/alpine.min.js" | sha256sum -c - >/dev/null 2>&1 || \
		{ echo "ERROR: static/js/alpine.min.js is missing or not the expected build."; \
		  echo "       Run 'make download-static'."; exit 1; }
	@echo "Static assets OK."

browser-test: check-static ## Browser smoke test (starts a server + Chromium; slower than `make test`)
	PYTHONPATH=backend $(PY) tests/browser_smoke.py
