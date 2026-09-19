"""Vercel serverless entrypoint.

Vercel's Python runtime looks for functions under `api/` relative to the project
root, and this project's root is the `api/` directory itself -- hence the
doubled path. The module exports the same ASGI app that `uvicorn app.main:app`
serves locally; there is no separate production code path.

Routing note: vercel.json uses `routes`, not `rewrites`. A rewrite now hands the
function the REWRITTEN path, so FastAPI would see `/api/index` for every request
and 404 everything; `routes` passes the original URL through, which is what an
ASGI app expects. (vercel.json permits no comments, so it is recorded here.)

What does NOT run here: the background worker (TDD §12.1). Auto-release sweeps,
reminders and the nightly rollups need a process that outlives a request. See
TDD §14.5 for what that means for a Vercel deployment.
"""

import sys
from pathlib import Path

# The function's working directory is the project root, but the bundle root is
# not on sys.path by default.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app

# Vercel's Python runtime detects a module-level ASGI application named `app`.
__all__ = ["app"]
