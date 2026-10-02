"""Serving the floor picture: signed links, and where the drawings come from.

The image URL is fetched by the Teams CLIENT, not by the bot, with no bot
token and no Deskify token -- so the link has to carry its own authority. It is
signed (HMAC) over floor, day, user and expiry: it shows that user's view of
that floor on that day ("mine" is per user) and nothing else, and it stops
working after `LINK_TTL_S`. Free/taken is what any employee already sees in
the app, but an unsigned /floor/{id}.png would show it to anyone at all.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import httpx

#: Long enough to scroll back to a card and tap the picture; short enough that
#: a forwarded link is not a standing window into the office.
LINK_TTL_S = 30 * 60


class Signer:
    def __init__(self, secret: bytes, clock=time.time):
        self._secret = secret
        self._clock = clock

    def _sig(self, floor_id: str, on: str, email: str, exp: int) -> str:
        msg = f"{floor_id}|{on}|{email}|{exp}".encode()
        digest = hmac.new(self._secret, msg, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def query(self, floor_id: str, on: date, email: str) -> str:
        exp = int(self._clock()) + LINK_TTL_S
        return urlencode({"on": on.isoformat(), "u": email, "exp": exp,
                          "sig": self._sig(floor_id, on.isoformat(), email, exp)})

    def verify(self, floor_id: str, on: str, email: str, exp: str, sig: str) -> bool:
        try:
            expires = int(exp)
        except ValueError:
            return False
        if expires < self._clock():
            return False
        return hmac.compare_digest(self._sig(floor_id, on, email, expires), sig)


class PlanSource:
    """The app's floor drawings, by plan_asset_key.

    Either a directory (the repo's client/public/plans, mounted into the
    container) or the web app's origin, which serves the same files at
    /plans/<key>.svg. Drawings change only on deploy, so they are cached for
    the life of the process.
    """

    def __init__(self, location: str):
        self._location = location.rstrip("/")
        self._cache: dict[str, str] = {}

    async def svg(self, key: str) -> str | None:
        if key in self._cache:
            return self._cache[key]
        if not key.replace("-", "").replace("_", "").isalnum():
            return None  # it becomes a path or a URL; never let it climb out
        if self._location.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=10.0) as http:
                r = await http.get(f"{self._location}/plans/{key}.svg")
            if r.status_code != 200:
                return None
            text = r.text
        else:
            path = Path(self._location) / f"{key}.svg"
            if not path.is_file():
                return None
            text = path.read_text()
        self._cache[key] = text
        return text
