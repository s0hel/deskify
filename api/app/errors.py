"""RFC 9457 problem+json. TDD §5.4."""

from fastapi import Request
from fastapi.responses import JSONResponse

BASE = "https://deskflow.app/errors"


class DeskflowError(Exception):
    status = 400
    code = "BAD_REQUEST"
    title = "Bad request"

    def __init__(self, detail: str = "", **extra):
        self.detail = detail
        self.extra = extra
        super().__init__(detail)

    def to_problem(self) -> dict:
        body = {
            "type": f"{BASE}/{self.code.lower().replace('_', '-')}",
            "title": self.title,
            "status": self.status,
            "code": self.code,
        }
        if self.detail:
            body["detail"] = self.detail
        body.update(self.extra)
        return body


class ResourceTaken(DeskflowError):
    status, code, title = 409, "RESOURCE_TAKEN", "That resource was just taken"


class CapacityExceeded(DeskflowError):
    status, code, title = 409, "CAPACITY_EXCEEDED", "The site is full for that day"


class PolicyDenied(DeskflowError):
    status, code, title = 409, "POLICY_DENIED", "Booking refused"


class RequestInProgress(DeskflowError):
    status, code, title = 409, "REQUEST_IN_PROGRESS", "That request is still running"


class BookingReleased(DeskflowError):
    status, code, title = 410, "BOOKING_RELEASED", "That booking was released"


class IdempotencyKeyReused(DeskflowError):
    status, code, title = 422, "IDEMPOTENCY_KEY_REUSED", "Idempotency key reused with a different body"


class NotFound(DeskflowError):
    # Cross-tenant access returns 404, never 403: a 403 confirms the object
    # exists. TDD §15.1.
    status, code, title = 404, "NOT_FOUND", "Not found"


async def handle(request: Request, exc: DeskflowError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=exc.to_problem(),
        media_type="application/problem+json",
    )
