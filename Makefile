# Developer commands for ATLAS Global Bank. Run `make help` for the list.
.DEFAULT_GOAL := help
SHELL := /bin/bash

BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin

.PHONY: help
help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Install backend (venv) and frontend dependencies
	python3 -m venv $(BACKEND)/.venv
	$(PY)/pip install -e "$(BACKEND)[dev]"
	cd $(FRONTEND) && npm install

.PHONY: migrate
migrate: ## Apply database migrations
	cd $(BACKEND) && .venv/bin/alembic upgrade head

.PHONY: backend
backend: ## Run the API with auto-reload on http://localhost:8000
	cd $(BACKEND) && .venv/bin/uvicorn app.main:app --reload --port 8000

.PHONY: frontend
frontend: ## Run the web UI on http://localhost:5173
	cd $(FRONTEND) && npm run dev

.PHONY: test
test: test-backend test-frontend ## Run backend and frontend unit tests

.PHONY: test-backend
test-backend: ## Run backend tests (needs PostgreSQL and the atlas_test database)
	cd $(BACKEND) && .venv/bin/pytest

.PHONY: test-frontend
test-frontend: ## Typecheck and run frontend unit tests
	cd $(FRONTEND) && npm run typecheck && npm test

.PHONY: test-e2e
test-e2e: ## Run Playwright end-to-end tests (starts backend and frontend if needed)
	cd $(FRONTEND) && npm run test:e2e

.PHONY: lint
lint: ## Lint and format-check the backend
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/ruff format --check .

.PHONY: validate
validate: ## Check a running stack end to end
	python3 scripts/validate_system.py

.PHONY: up
up: ## Start the full stack with Docker Compose
	docker compose up --build

.PHONY: down
down: ## Stop the Docker Compose stack
	docker compose down
