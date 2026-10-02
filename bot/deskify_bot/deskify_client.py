"""A thin client for the endpoints the web app already uses.

Nothing here is bot-specific API surface: if the bot needs something the API
does not offer, that is an API change to argue for in api/, not a shortcut to
take here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

#: Mirrors client/src/api/messages.ts. The API sends codes, not sentences
#: (FR-6.9), so every surface that says "no" owns its wording.
DENIAL_TEXT: dict[str, str] = {
    "RESOURCE_TAKEN": "Someone booked that desk a moment ago.",
    "CAPACITY_EXCEEDED": "The office is full that day ({cap} places).",
    "SITE_CLOSED": "The office is closed that day: {reason}.",
    "OUTSIDE_OPENING_HOURS": "That site is open {opens}–{closes}.",
    "RESOURCE_UNAVAILABLE": "That desk is out of service.",
    "ZONE_RESTRICTED": "That area is reserved for another team.",
    "DESK_ASSIGNED": "That desk belongs to someone else.",
    # No {desk}: a refusal caught by the database constraint (a concurrent
    # request) arrives without one, and str.format would fall back to "Booking
    # refused".
    "ALREADY_HAVE_DESK": "You already have a desk booked for that time.",
    "BOOKING_HORIZON_EXCEEDED": "You can book up to {limit_days} days ahead.",
    "MAX_FUTURE_BOOKINGS": "You already have {limit} upcoming bookings.",
    "BOOKING_RELEASED": "That booking was released because it wasn't checked into.",
}


@dataclass
class ApiError(Exception):
    status: int
    code: str
    detail: str = ""
    denials: list[dict[str, Any]] = field(default_factory=list)

    def explain(self) -> str:
        """One sentence a person can act on."""
        code = self.denials[0]["code"] if self.denials else self.code
        params = self.denials[0].get("params", {}) if self.denials else {}
        template = DENIAL_TEXT.get(code)
        if template:
            try:
                return template.format(**params)
            except (KeyError, IndexError):
                pass
        return self.detail or "That booking isn't allowed."


def free_desks(floor: dict, states: dict[str, str]) -> list[dict]:
    desks = [r for r in floor["resources"]
             if r["kind"] == "desk" and states.get(r["id"]) == "free"]
    return sorted(desks, key=lambda r: r["name"])


class DeskifyClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None):
        self._http = http or httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, path: str, token: str | None = None, **kw) -> Any:
        headers = {"authorization": f"Bearer {token}"} if token else {}
        r = await self._http.request(method, path, headers=headers, **kw)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}
            raise ApiError(
                status=r.status_code,
                code=body.get("code", "HTTP_ERROR"),
                detail=body.get("detail") or body.get("title") or r.reason_phrase,
                denials=body.get("denials") or [],
            )
        return r.json() if r.content else None

    # --- auth -------------------------------------------------------------

    async def dev_sign_in(self, email: str) -> tuple[str, int]:
        """The same two legs the web client takes: a one-time code, then a token."""
        code = (await self._call("POST", "/auth/dev-sign-in", json={"email": email}))["code"]
        tok = await self._call("POST", "/auth/token", json={"code": code})
        return tok["access_token"], tok["expires_in"]

    # --- reads ------------------------------------------------------------

    async def me(self, token: str) -> dict:
        return await self._call("GET", "/me", token)

    async def sites(self, token: str) -> list[dict]:
        return await self._call("GET", "/sites", token)

    async def floors(self, token: str, site_id: str, on: date) -> list[dict]:
        return await self._call(
            "GET", f"/sites/{site_id}/floors", token, params={"on": on.isoformat()}
        )

    async def floor(self, token: str, floor_id: str) -> dict:
        return await self._call("GET", f"/floors/{floor_id}", token)

    async def floor_states(self, token: str, floor_id: str, on: date) -> dict[str, str]:
        state = await self._call(
            "GET", f"/floors/{floor_id}/state", token, params={"on": on.isoformat()}
        )
        return state["states"]

    async def free_desks(self, token: str, floor_id: str, on: date) -> list[dict]:
        """Desks on a floor that this user can book on `on`, by name."""
        floor = await self.floor(token, floor_id)
        states = await self.floor_states(token, floor_id, on)
        return free_desks(floor, states)

    async def bookings(self, token: str) -> list[dict]:
        return await self._call("GET", "/bookings", token)

    async def resource_names(self, token: str) -> dict[str, str]:
        """id -> "Desk · Floor · Office" for every resource, for labelling bookings.

        BookingOut carries only a resource id, and a booking list can span
        offices, so this walks the org. A handful of floor reads, done only
        when someone opens "My bookings".
        """
        names: dict[str, str] = {}
        for site in await self.sites(token):
            for f in await self._call("GET", f"/sites/{site['id']}/floors", token):
                floor = await self._call("GET", f"/floors/{f['id']}", token)
                for r in floor["resources"]:
                    names[r["id"]] = f"{r['name']} · {floor['name']} · {site['name']}"
        return names

    # --- writes -----------------------------------------------------------

    async def book(self, token: str, resource_id: str, on: date) -> dict:
        return await self._call(
            "POST", "/bookings", token,
            json={"resource_id": resource_id, "on": on.isoformat(), "slot": "day"},
        )

    async def cancel(self, token: str, booking_id: str) -> None:
        await self._call("DELETE", f"/bookings/{booking_id}", token)
