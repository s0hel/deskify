import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.errors import DeskifyError, handle
from app.routers import auth, core, people

structlog.configure(processors=[structlog.processors.add_log_level,
                                structlog.processors.TimeStamper(fmt="iso"),
                                structlog.processors.JSONRenderer()])

app = FastAPI(
    title="Deskify API",
    version="0.1.0",
    description="Phase 0 skeleton. See docs/TECHNICAL_DESIGN.md.",
)
# Explicit origins, never a wildcard -- settings refuse one outside dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    # PUT belongs here: /me/privacy, /me/home-site and /me/declarations/{on}
    # are all PUT, and a missing method fails at the preflight, so the browser
    # reports a CORS error rather than anything about the endpoint.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["authorization", "content-type", "idempotency-key"],
)

app.add_exception_handler(DeskifyError, handle)
app.include_router(auth.router)
app.include_router(core.router)
app.include_router(people.router)

# /auth/dev-sign-in issues a valid token for any known email with no
# credential, so it is mounted only where it has been asked for: in dev, or
# where DESKIFY_ALLOW_DEV_SIGN_IN was set deliberately. Everywhere else the
# route genuinely does not exist rather than existing and refusing, and an
# unconfigured deployment lands there by default (app/config.py).
if settings.dev_sign_in_enabled:
    app.include_router(auth.dev_router)

if settings.dev_sign_in_is_exposed:
    # Loud, once, on every cold start. Someone reading these logs months from
    # now should not have to infer this from a config diff.
    structlog.get_logger().warning(
        "dev_sign_in_exposed",
        environment=settings.environment,
        detail=(
            "/auth/dev-sign-in is mounted outside dev. It issues a valid token "
            "for any known email with no credential, so anyone who can reach "
            "this API can sign in as any user in it."
        ),
    )


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
