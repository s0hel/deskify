"""The booking write path. TDD §4.

The application's job here is small by design: evaluate policy, take the
capacity lock only when a cap exists, insert, and translate one IntegrityError.
There is no SELECT ... FOR UPDATE on the resource, no advisory lock, and no
optimistic retry loop -- the exclusion constraint does that work.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import CapacityExceeded, NotFound, PolicyDenied, ResourceTaken
from app.models import Booking, Resource, Site, SiteDayCapacity, Zone
from app.policy import PolicyContext, evaluate
from app.repository import TenantRepository
from app.timezone import local_date_of, parse_opening_hours

DOUBLE_ALLOCATION_CONSTRAINT = "booking_no_double_allocation"

#: deadlock_detected, serialization_failure.
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})


def _sqlstate(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    return getattr(cause, "sqlstate", None)


async def with_booking_txn(maker, fn, *, attempts: int = 3):
    """Owns the transaction for a booking write, and retries transient
    serialization failures.

    PHASE 0 FINDING (see TDD §4.1). Under genuinely concurrent inserts against
    one resource, Postgres does not always produce a simple wait chain on the
    exclusion constraint -- with many waiters it can detect a deadlock and abort
    a transaction that would otherwise have WON the race.

    Without a retry, that surfaces to the user as "this desk was just taken"
    for a desk that is in fact free, at exactly the Monday-morning moment when
    it is most visible. The retry is bounded and specific to these two
    SQLSTATEs; it is not a general optimistic-concurrency loop, and it does not
    weaken the constraint, which remains the thing that decides the winner.
    """
    last: BaseException | None = None
    for attempt in range(attempts):
        async with maker() as session:
            try:
                result = await fn(session)
                await session.commit()
                return result
            except DBAPIError as exc:
                await session.rollback()
                if _sqlstate(exc) in RETRYABLE_SQLSTATES and attempt < attempts - 1:
                    last = exc
                    await asyncio.sleep(0.005 * (2**attempt))
                    continue
                raise
    raise last  # pragma: no cover


async def build_context(
    session: AsyncSession,
    repo: TenantRepository,
    *,
    user_id: uuid.UUID,
    resource: Resource,
    site: Site,
    start: datetime,
    end: datetime,
    now: datetime,
    policy_values: dict | None = None,
) -> PolicyContext:
    """Load everything the rules need, once. TDD §4.3."""
    local_date = local_date_of(start, site.timezone)
    opens, closes = parse_opening_hours(site.opening_hours)

    future = await session.execute(
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.organization_id == repo.organization_id,
            Booking.user_id == user_id,
            Booking.local_date >= now.date(),
            Booking.status.notin_(("cancelled", "released_no_show")),
        )
    )

    zone_group = None
    if resource.zone_id:
        zone = await repo.get(Zone, resource.zone_id)
        zone_group = str(zone.restricted_to_group_id) if zone and zone.restricted_to_group_id else None

    booked = 0
    if site.capacity_cap is not None:
        booked = (
            await session.execute(
                select(func.coalesce(SiteDayCapacity.booked_count, 0)).where(
                    SiteDayCapacity.site_id == site.id,
                    SiteDayCapacity.local_date == local_date,
                )
            )
        ).scalar() or 0

    return PolicyContext(
        now=now,
        requested_start=start,
        requested_end=end,
        local_date=local_date,
        site_timezone=site.timezone,
        site_opens=opens,
        site_closes=closes,
        rules=policy_values or {},
        user_future_booking_count=future.scalar() or 0,
        resource_status=resource.status,
        resource_assigned_user_id=str(resource.assigned_user_id)
        if resource.assigned_user_id
        else None,
        user_id=str(user_id),
        zone_restricted_to_group_id=zone_group,
        site_booked_count=booked,
        site_capacity_cap=site.capacity_cap,
    )


async def create_booking(
    session: AsyncSession,
    repo: TenantRepository,
    *,
    user_id: uuid.UUID,
    resource_id: uuid.UUID,
    start: datetime,
    end: datetime,
    now: datetime,
    created_by: uuid.UUID | None = None,
    policy_values: dict | None = None,
) -> Booking:
    resource = await repo.get(Resource, resource_id)
    if resource is None:
        raise NotFound("resource")
    site = await repo.get(Site, resource.site_id)
    if site is None:
        raise NotFound("site")

    ctx = await build_context(
        session, repo, user_id=user_id, resource=resource, site=site,
        start=start, end=end, now=now, policy_values=policy_values,
    )
    denials = evaluate(ctx)
    if denials:
        raise PolicyDenied(denials=[d.as_dict() for d in denials])

    local_date = ctx.local_date

    # TDD §4.2 -- sites WITHOUT a cap skip this entirely and take the lock-free
    # path. Most will. This is the one genuine serialization point.
    if site.capacity_cap is not None:
        await session.execute(
            text(
                """
                INSERT INTO site_day_capacity
                    (organization_id, site_id, local_date, booked_count, cap)
                VALUES (:org, :site, :d, 0, :cap)
                ON CONFLICT (site_id, local_date) DO NOTHING
                """
            ),
            {"org": repo.organization_id, "site": site.id, "d": local_date, "cap": site.capacity_cap},
        )
        row = (
            await session.execute(
                text(
                    "SELECT booked_count, cap FROM site_day_capacity "
                    "WHERE site_id = :site AND local_date = :d FOR UPDATE"
                ),
                {"site": site.id, "d": local_date},
            )
        ).first()
        if row and row.cap is not None and row.booked_count >= row.cap:
            raise CapacityExceeded(cap=row.cap, booked=row.booked_count)
        await session.execute(
            text(
                "UPDATE site_day_capacity SET booked_count = booked_count + 1 "
                "WHERE site_id = :site AND local_date = :d"
            ),
            {"site": site.id, "d": local_date},
        )

    booking = repo.add(
        Booking(
            site_id=site.id,
            resource_id=resource.id,
            user_id=user_id,
            # Bounds are ALWAYS explicit and half-open. '[)' is what makes
            # 09:00-13:00 and 13:00-17:00 two bookings rather than a conflict
            # (TDD §4.4). Relying on a library default here would be a
            # correctness bug waiting for a dependency upgrade.
            during=Range(start, end, bounds="[)"),
            local_date=local_date,
            status="confirmed",
            created_by=created_by or user_id,
        )
    )

    try:
        await session.flush()
    except IntegrityError as exc:
        # The ONLY concurrency handling in the booking path. TDD §4.1.
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        if constraint == DOUBLE_ALLOCATION_CONSTRAINT or DOUBLE_ALLOCATION_CONSTRAINT in str(exc):
            raise ResourceTaken(resource_id=str(resource_id)) from exc
        raise
    return booking
