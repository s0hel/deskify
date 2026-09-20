"""RFC 9457 problem+json. TDD §5.4."""

from fastapi import Request
from fastapi.responses import JSONResponse

#: A URN, not an https:// URL. The old base pointed at deskflow.app -- a domain
#: nobody here owns, which today serves a "this domain is available" parking
#: page. RFC 9457 only asks that `type` IDENTIFY the problem; it does not have
#: to resolve. An identifier anyone can buy is worse than one that resolves to
#: nothing, because it can start resolving to someone else's content.
#:
#: Swap this for https://<a domain we own>/errors/... the day there is one, and
#: put real documentation behind it. Clients match on `code`, not `type`
#: (client/src/api/client.ts), so this base is free to move.
BASE = "urn:deskify:error"


class DeskifyError(Exception):
    status = 400
    code = "BAD_REQUEST"
    title = "Bad request"

    def __init__(self, detail: str = "", **extra):
        self.detail = detail
        self.extra = extra
        super().__init__(detail)

    def to_problem(self) -> dict:
        body = {
            "type": f"{BASE}:{self.code.lower().replace('_', '-')}",
            "title": self.title,
            "status": self.status,
            "code": self.code,
        }
        if self.detail:
            body["detail"] = self.detail
        body.update(self.extra)
        return body


class ResourceTaken(DeskifyError):
    status, code, title = 409, "RESOURCE_TAKEN", "That resource was just taken"


class CapacityExceeded(DeskifyError):
    status, code, title = 409, "CAPACITY_EXCEEDED", "The site is full for that day"


class PolicyDenied(DeskifyError):
    status, code, title = 409, "POLICY_DENIED", "Booking refused"


class RequestInProgress(DeskifyError):
    status, code, title = 409, "REQUEST_IN_PROGRESS", "That request is still running"


class BookingReleased(DeskifyError):
    status, code, title = 410, "BOOKING_RELEASED", "That booking was released"


class IdempotencyKeyReused(DeskifyError):
    status, code, title = 422, "IDEMPOTENCY_KEY_REUSED", "Idempotency key reused with a different body"


class NotFound(DeskifyError):
    # Cross-tenant access returns 404, never 403: a 403 confirms the object
    # exists. TDD §15.1.
    status, code, title = 404, "NOT_FOUND", "Not found"


async def handle(request: Request, exc: DeskifyError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=exc.to_problem(),
        media_type="application/problem+json",
    )
