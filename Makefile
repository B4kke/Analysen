.PHONY: install dev-api worker web test lint nim-smoke compose-up compose-down lock migrate test-integration

install:
	python -m pip install -r requirements-dev.lock
	cd apps/web && npm ci

playwright:
	python -m playwright install chromium

dev-api:
	uvicorn apps.api.app.main:app --reload --port 8000

worker:
	dramatiq apps.worker.app.tasks -p 2 -t 4

web:
	cd apps/web && npm run dev

test:
	pytest -q

lint:
	ruff check .
	mypy apps

nim-smoke:
	python scripts/nim_smoke.py --suite text

compose-up:
	docker compose up --build

compose-down:
	docker compose down

lock:
	uv pip compile requirements.txt -o requirements.lock
	uv pip compile requirements-dev.txt -o requirements-dev.lock
	uv pip compile requirements-research.txt -o requirements-research.lock

migrate:
	alembic upgrade head

test-integration:
	pytest -q tests/integration
