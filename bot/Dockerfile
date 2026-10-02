FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

# The floor pictures are rasterised with resvg, which draws text only in fonts
# it can find. A slim image has none, and without one every desk label on the
# plan silently disappears.
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY deskify_bot ./deskify_bot

EXPOSE 3978
CMD ["uv", "run", "--no-dev", "python", "-m", "deskify_bot.app"]
