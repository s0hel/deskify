import structlog
from fastapi import FastAPI

from app.errors import DeskflowError, handle
from app.routers import auth, core

structlog.configure(processors=[structlog.processors.add_log_level,
                                structlog.processors.TimeStamper(fmt="iso"),
                                structlog.processors.JSONRenderer()])

app = FastAPI(
    title="deskflow API",
    version="0.1.0",
    description="Phase 0 skeleton. See docs/TECHNICAL_DESIGN.md.",
)
app.add_exception_handler(DeskflowError, handle)
app.include_router(auth.router)
app.include_router(core.router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
