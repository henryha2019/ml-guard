.PHONY: help dev up down fmt lint test db-migrate \
        dashboard dashboard-build dashboard-logs validate

help:
	@echo ""
	@echo "Core:"
	@echo "  make dev        Run full stack (foreground)"
	@echo "  make up         Run full stack (detached)"
	@echo "  make down       Stop stack and remove volumes"
	@echo ""
	@echo "Quality:"
	@echo "  make fmt        Format backend code (ruff)"
	@echo "  make lint       Lint backend code (ruff)"
	@echo "  make test       Run backend tests"
	@echo ""
	@echo "Database:"
	@echo "  make db-migrate Apply alembic migrations"
	@echo ""
	@echo "Validation:"
	@echo "  make validate   Run full local validation"
	@echo ""
	@echo "Dashboard:"
	@echo "  make dashboard        Run dashboard only"
	@echo "  make dashboard-build  Build dashboard image"
	@echo "  make dashboard-logs   Tail dashboard logs"
	@echo ""

# -------------------------
# Core stack
# -------------------------
dev:
	docker compose up --build

up:
	docker compose up -d

down:
	docker compose down -v

# -------------------------
# Code quality
# -------------------------
fmt:
	cd backend && python -m ruff format .
	cd backend && python -m ruff check . --fix

lint:
	cd backend && python -m ruff check .

test:
	cd backend && python -m pytest -q

# -------------------------
# Database
# -------------------------
db-migrate:
	cd backend && alembic upgrade head

# -------------------------
# Validation
# -------------------------
validate:
	./validation.sh

# -------------------------
# Dashboard
# -------------------------
dashboard-build:
	docker compose build dashboard

dashboard:
	docker compose up -d dashboard

dashboard-logs:
	docker compose logs -f dashboard
