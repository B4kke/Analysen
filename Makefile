.PHONY: install dev-api worker web test lint compose-up compose-down

install:
	python -m pip install -r requirements-dev.txt
	cd apps/web && npm install

playwright:
	python -m playwright install chromium

dev-api:
	uvicorn apps.api.app.main:app --reload --port 8000

worker:
	dramatiq apps.worker.app.tasks

web:
	cd apps/web && npm run dev

test:
	pytest -q

lint:
	ruff check .
	mypy apps

compose-up:
	docker compose up --build

compose-down:
	docker compose down
