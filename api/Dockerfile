# The API in a container, for the local Teams stack (docker compose --profile teams).
# Vercel does not use this; it builds from pyproject.toml directly.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

EXPOSE 8099
ENTRYPOINT ["./docker-entrypoint.sh"]
