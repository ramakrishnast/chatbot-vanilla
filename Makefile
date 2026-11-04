SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose --env-file .env
BACKEND := cd backend &&
FRONTEND := cd frontend &&

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.env:
	cp .env.example .env

.PHONY: setup
setup: .env ## Install backend + frontend dependencies and create .env
	$(BACKEND) uv sync
	$(FRONTEND) npm install

.PHONY: hooks
hooks: ## Install the git pre-commit hooks
	uvx pre-commit install

# ---------------------------------------------------------------- database
.PHONY: db-up
db-up: .env ## Start Postgres in Docker and wait until it is healthy
	$(COMPOSE) up -d --wait postgres

.PHONY: db-down
db-down: ## Stop Postgres (data is kept in the pgdata volume)
	$(COMPOSE) down

.PHONY: db-logs
db-logs: ## Follow Postgres logs
	$(COMPOSE) logs -f postgres

.PHONY: db-shell
db-shell: ## Open psql inside the Postgres container
	$(COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

.PHONY: db-reset
db-reset: ## DANGER: delete all chat history and recreate the database
	$(COMPOSE) down -v
	$(MAKE) db-up migrate

.PHONY: migrate
migrate: ## Apply database migrations
	$(BACKEND) uv run alembic upgrade head

.PHONY: migration
migration: ## Create a migration from model changes: make migration m="describe change"
	$(BACKEND) uv run alembic revision --autogenerate -m "$(m)"

# ---------------------------------------------------------------- run
.PHONY: dev
dev: ## Run backend (:8000) and frontend (:5173) with hot reload
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload --port 8000 --no-access-log) & \
	(cd frontend && npm run dev) & \
	wait

.PHONY: backend
backend: ## Run only the backend with hot reload
	$(BACKEND) uv run uvicorn app.main:app --reload --port 8000 --no-access-log

.PHONY: frontend
frontend: ## Run only the frontend dev server
	$(FRONTEND) npm run dev

.PHONY: build
build: ## Build the frontend into frontend/dist
	$(FRONTEND) npm run build

.PHONY: start
start: build ## Production-style run: one server on :8000 serving API + built UI
	$(BACKEND) uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --no-access-log

# ---------------------------------------------------------------- quality
.PHONY: test
test: test-backend test-frontend ## Run all tests

.PHONY: test-backend
test-backend: ## Run backend tests (needs `make db-up`)
	$(BACKEND) uv run pytest

.PHONY: test-frontend
test-frontend: ## Run frontend tests
	$(FRONTEND) npm test

.PHONY: lint
lint: ## Lint and type-check everything
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy .
	$(FRONTEND) npm run lint && npm run format:check && npm run typecheck

.PHONY: format
format: ## Auto-format everything
	$(BACKEND) uv run ruff check --fix . && uv run ruff format .
	$(FRONTEND) npm run format
