.DEFAULT_GOAL := help
SHELL := /bin/bash
UV := uv run
PHASE ?= 0

# Prerequisite checks with install hints (README: Prerequisites).
ifeq ($(shell command -v uv 2>/dev/null),)
$(error uv is not installed. Install it with `brew install uv` (or `curl -LsSf https://astral.sh/uv/install.sh | sh`), then open a new terminal)
endif

.PHONY: help install fmt lint typecheck test test-model e2e check trace db-up db-down instance migration seed backup backups restore copy-to-dev model reindex

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

test-model: ## Tests with the real search-by-meaning model (needs `make model` first)
	$(UV) pytest -m model --no-cov

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

seed: ## Load ~50 sample contacts into a dev instance: make seed I=dev [RESET=1] (refused in production)
	@test -n "$(I)" || (echo "usage: make seed I=<instance> [RESET=1]" && exit 2)
	INSTANCE_ENV_FILE=instances/$(I).env $(UV) python -m scripts.seed $(if $(RESET),--reset)

model: ## Install the search-by-meaning model once (~90 MB, checksum-verified): make model [FROM=<folder>]
	$(UV) python -m scripts.semantic model $(if $(FROM),--from "$(FROM)")

reindex: ## Embed every contact for search by meaning now: make reindex I=dev
	@test -n "$(I)" || (echo "usage: make reindex I=<instance>" && exit 2)
	INSTANCE_ENV_FILE=instances/$(I).env $(UV) python -m scripts.semantic reindex

backup: ## Back up an instance now and prune old backups: make backup I=business-prod
	@test -n "$(I)" || (echo "usage: make backup I=<instance>" && exit 2)
	INSTANCE_ENV_FILE=instances/$(I).env $(UV) python -m scripts.backup backup

backups: ## List an instance's backups: make backups I=business-prod
	@test -n "$(I)" || (echo "usage: make backups I=<instance>" && exit 2)
	INSTANCE_ENV_FILE=instances/$(I).env $(UV) python -m scripts.backup list

restore: ## Restore a backup (stop the app first): make restore I=dev FILE=<name> [YES=1 for production]
	@test -n "$(I)" -a -n "$(FILE)" || (echo "usage: make restore I=<instance> FILE=<backup> [YES=1]" && exit 2)
	INSTANCE_ENV_FILE=instances/$(I).env $(UV) python -m scripts.backup restore "$(FILE)" $(if $(YES),--yes)

copy-to-dev: ## Copy an instance into a dev one: make copy-to-dev FROM=business-prod TO=dev [ANONYMIZE=1]
	@test -n "$(FROM)" -a -n "$(TO)" || (echo "usage: make copy-to-dev FROM=<instance> TO=<dev instance> [ANONYMIZE=1]" && exit 2)
	INSTANCE_ENV_FILE=instances/$(TO).env $(UV) python -m scripts.backup copy-to-dev --from-env instances/$(FROM).env $(if $(ANONYMIZE),--anonymize)

migration: ## New Alembic migration from model changes: make migration m="add tags" (uses the dev instance)
	@test -n "$(m)" || (echo 'usage: make migration m="message"' && exit 2)
	INSTANCE_ENV_FILE=instances/dev.env $(UV) alembic revision --autogenerate -m "$(m)"
