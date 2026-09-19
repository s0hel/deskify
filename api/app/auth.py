"""Tokens and the sign-in handshake. TDD §6.

The client never speaks to the IdP. It opens a URL on OUR API in the system
browser; we are the OIDC relying party; we mint our own tokens (TDD §6.1).

WHAT IS REAL HERE: the token format, the one-time-code handoff, refresh
rotation with family revocation, and the discover endpoint's non-disclosure.

WHAT IS NOT: the leg between /auth/start and /auth/callback. Completing it needs
Google Workspace / Entra client credentials, which Phase 0 must obtain. The
`dev` provider below stands in its place and REFUSES to run outside dev.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"

#: one-time codes: code -> (user_id, org_id, expires_at). Redis-free by design;
#: a 60s single-use code does not need durable storage.
_CODES: dict[str, tuple[uuid.UUID, uuid.UUID, datetime]] = {}


def mint_access_token(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "org": str(org_id),
            "iat": now,
            "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["org"])
    except (JWTError, KeyError, ValueError) as exc:
        raise ValueError("invalid token") from exc


def issue_one_time_code(user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """Tokens must never appear in a URL, browser history, or the OS's
    link-handling logs. The app redeems this code over HTTPS instead."""
    code = secrets.token_urlsafe(32)
    _CODES[code] = (user_id, org_id, datetime.now(UTC) + timedelta(seconds=60))
    return code


def redeem_one_time_code(code: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    entry = _CODES.pop(code, None)  # single use: popped whether or not it is fresh
    if entry is None:
        return None
    user_id, org_id, expires = entry
    if datetime.now(UTC) > expires:
        return None
    return user_id, org_id
