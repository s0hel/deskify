#!/bin/sh
# Migrate, seed ONLY an empty database, then serve.
#
# The seed starts with DELETE FROM every table, so running it on every boot
# would wipe whatever you booked through the bot or `make web` each time the
# container restarts. It runs once, against a database with no organization.
# To start over, `make seed` from the host as usual.
set -e

uv run --no-dev alembic upgrade head

empty=$(uv run --no-dev python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.db import SessionLocal

async def main():
    async with SessionLocal() as s:
        n = (await s.execute(text("SELECT count(*) FROM organization"))).scalar_one()
    print("yes" if n == 0 else "no")

asyncio.run(main())
EOF
)

if [ "$empty" = "yes" ]; then
  # --yes: the seed refuses any host that is not literally localhost, and
  # inside compose the database is "db". It is still the local container.
  uv run --no-dev python -m app.seed --yes
fi

exec uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port 8099
