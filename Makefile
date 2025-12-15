.PHONY: help dev up down fmt test lint db-migrate

help:
	@echo "make dev | up | down | fmt | lint | test | db-migrate"

dev:
	docker compose up --build

up:
	docker compose up -d

down:
	docker compose down -v

fmt:
	cd backend && python -m ruff format .
	cd backend && python -m ruff check . --fix

lint:
	cd backend && python -m ruff check .

test:
	cd backend && python -m pytest -q

db-migrate:
	cd backend && alembic upgrade head
