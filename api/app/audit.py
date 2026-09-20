"""The admin audit trail. FR-8.8.

One function, called from the admin handlers. It writes into the caller's
transaction rather than committing on its own, so a change and the record of
it land together or not at all -- an audit log that can disagree with the data
is worse than none, because it is believed.

`detail` is where the BEFORE value goes. An entry saying "site updated" is
almost useless six months later; one saying the cap went from 120 to 60 is the
answer to the question someone will actually be asking.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    **detail,
) -> AuditLog:
    entry = AuditLog(
        organization_id=organization_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=_jsonable(detail),
    )
    session.add(entry)
    return entry


def _jsonable(value):
    """UUIDs and dates are the two things that reach this and are not JSON.

    Serialising them here rather than at each call site means a handler cannot
    write an audit row that fails to insert on a type nobody thought about.
    """
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
