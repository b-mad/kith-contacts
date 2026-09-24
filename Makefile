.DEFAULT_GOAL := help
SHELL := /bin/bash
UV := uv run
PHASE ?= 0

# Prerequisite checks with install hints (README: Prerequisites).
ifeq ($(shell command -v uv 2>/dev/null),)
$(error uv is not installed. Install it with `brew install uv` (or `curl -LsSf https://astral.sh/uv/install.sh | sh`), then open a new terminal)
endif

.PHONY: help install fmt lint typecheck test e2e check trace db-up db-down instance migration

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install dependencies and git hooks
	uv sync
	$(UV) pre-commit install --hook-type pre-commit --hook-type commit-msg

fmt: ## Auto-format and fix lint issues
	$(UV) ruff format .
	$(UV) ruff check --fix .

lint: ## Format check + lint
	$(UV) ruff format --check .
	$(UV) ruff check .

typecheck: ## mypy --strict
	$(UV) mypy app scripts tests

test: ## Unit + integration tests with coverage (needs PostgreSQL)
	$(UV) pytest

e2e: ## Browser end-to-end tests (needs PostgreSQL + Playwright browsers)
	$(UV) pytest -m e2e --no-cov

check: lint typecheck test ## Everything CI runs — required before every commit

trace: ## Requirement -> test traceability (PHASE=n)
	$(UV) python -m scripts.req_trace --phase $(PHASE)

db-up: ## Start local PostgreSQL (Docker)
	@command -v docker >/dev/null || (echo 'Docker is not installed or not running: install Docker Desktop (https://www.docker.com/products/docker-desktop/) and start it' && exit 1)
	docker compose -f docker-compose.db.yml up -d --wait

db-down: ## Stop local PostgreSQL (data is kept)
	docker compose -f docker-compose.db.yml down

instance: ## Create an instance: make instance NAME=dev PORT=5180 ENV=development [COLOR=#hex TYPES=a,b]
	@test -n "$(NAME)" -a -n "$(PORT)" -a -n "$(ENV)" || (echo "usage: make instance NAME=.. PORT=.. ENV=development|production" && exit 2)
	$(UV) python -m scripts.bootstrap_instance --name "$(NAME)" --port "$(PORT)" --env "$(ENV)" \
		$(if $(COLOR),--color "$(COLOR)") $(if $(TYPES),--types "$(TYPES)")

migration: ## New Alembic migration from model changes: make migration m="add tags" (uses the dev instance)
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 2)
	INSTANCE_ENV_FILE=instances/dev.env $(UV) alembic revision --autogenerate -m "$(m)"
