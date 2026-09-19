import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.errors import DeskflowError, handle
from app.routers import auth, core, people

structlog.configure(processors=[structlog.processors.add_log_level,
                                structlog.processors.TimeStamper(fmt="iso"),
                                structlog.processors.JSONRenderer()])

app = FastAPI(
    title="deskflow API",
    version="0.1.0",
    description="Phase 0 skeleton. See docs/TECHNICAL_DESIGN.md.",
)
# Explicit origins, never a wildcard -- settings refuse one outside dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["authorization", "content-type", "idempotency-key"],
)

app.add_exception_handler(DeskflowError, handle)
app.include_router(auth.router)
app.include_router(core.router)
app.include_router(people.router)

# /auth/dev-sign-in mints a token for any user from an email alone. It is
# mounted only in dev, so in every other environment the route genuinely does
# not exist rather than existing and refusing. Settings default to prod, so an
# unconfigured deployment lands here (app/config.py).
if settings.is_dev:
    app.include_router(auth.dev_router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
