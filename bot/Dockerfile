FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY deskify_bot ./deskify_bot

EXPOSE 3978
CMD ["uv", "run", "--no-dev", "python", "-m", "deskify_bot.app"]
