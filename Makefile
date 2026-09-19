.PHONY: up down migrate seed api test test-api test-client build spike gen-api lint

# Settings fail closed: environment defaults to "prod", which refuses the
# development signing key and disables /auth/dev-sign-in. Local targets opt in.
export DESKFLOW_ENVIRONMENT = dev

up:            ## start Postgres
	docker compose up -d db

down:
	docker compose down

migrate: up
	cd api && uv run alembic upgrade head

seed: migrate
	cd api && uv run python -m app.seed

api: migrate
	cd api && uv run uvicorn app.main:app --reload --port 8099

test: test-api test-client

test-api: migrate
	cd api && uv run pytest -q

test-client:
	cd client && npm run typecheck && npm test

build:
	cd client && npm run build

spike: build       ## R8 gate -- open /spike.html on a real device
	cd client && npx vite preview --host --port 4173

gen-api:           ## regenerate the typed client from the live OpenAPI schema
	cd client && npm run gen:api

lint:
	cd api && uv run ruff check .
