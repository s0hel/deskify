.PHONY: up down migrate seed api web test test-api test-client build spike gen-api lint ios ios-open

# Settings fail closed: environment defaults to "prod", which refuses the
# development signing key and disables /auth/dev-sign-in. Local targets opt in.
export DESKIFY_ENVIRONMENT = dev

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

web:               ## the app, against a local API on :8099
	cd client && npm run dev

test: test-api test-client

test-api: migrate
	cd api && uv run pytest -q

test-client:
	cd client && npm run typecheck && npm test

build:
	cd client && npm run build

spike: build       ## R8 gate -- open /spike.html on a real device
	cd client && npx vite preview --host --port 4173

# The iOS bundle ships INSIDE the binary, so the API address is COMPILED IN --
# there is no runtime config and no localhost fallback (api/client.ts throws on
# a production build with no VITE_API_URL). Override per invocation:
#   make ios IOS_API_URL=https://deskify-api-pi.vercel.app
#
# The default is the local API. A simulator shares the host's network and iOS
# exempts loopback from App Transport Security, so cleartext http://localhost
# works with no Info.plist exception. A real DEVICE has neither -- point it at
# an https:// URL.
IOS_API_URL ?= http://localhost:8099

ios: migrate       ## build, sync, and run in the iOS simulator
	cd client && VITE_API_URL=$(IOS_API_URL) npm run build && npx cap sync ios && npx cap run ios

ios-open:          ## same, but hand the project to Xcode
	cd client && VITE_API_URL=$(IOS_API_URL) npm run build && npx cap sync ios && npx cap open ios

gen-api:           ## regenerate the typed client from the live OpenAPI schema
	cd client && npm run gen:api

lint:
	cd api && uv run ruff check .
