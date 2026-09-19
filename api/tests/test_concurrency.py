"""TDD §16.2 -- the proof that §4.1 works.

This is the test the whole design rests on. It fires N genuinely concurrent
booking attempts at one desk and asserts exactly one wins. If a refactor ever
reintroduces a read-then-write race, this fails.
"""

import asyncio

from app.booking_service import create_booking, with_booking_txn
from app.errors import CapacityExceeded, ResourceTaken
from app.repository import TenantRepository
from tests.conftest import NOW, berlin, make_org

N = 25


async def _attempt(maker, org_id, user_id, resource_id, start, end):
    """One independent session, its own transaction -- a real concurrent client.
    Goes through with_booking_txn, which is the production path."""

    async def work(s):
        repo = TenantRepository(s, org_id)
        return await create_booking(
            s, repo, user_id=user_id, resource_id=resource_id,
            start=start, end=end, now=NOW,
        )

    try:
        await with_booking_txn(maker, work)
        return "created"
    except ResourceTaken:
        return "taken"
    except CapacityExceeded:
        return "capacity"


async def test_concurrent_bookings_on_one_desk_produce_exactly_one_winner(
    db, sessionmaker_factory
):
    fx = await make_org(db)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    results = await asyncio.gather(*[
        _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id, fx["desk"].id, start, end)
        for _ in range(N)
    ])

    assert results.count("created") == 1, f"expected exactly one winner, got {results}"
    assert results.count("taken") == N - 1


async def test_overlapping_half_days_collide(db, sessionmaker_factory):
    """Half-day bookings are why the constraint ranges over time rather than
    keying on a date (TDD §4.4). 09:00-13:00 and 12:00-17:00 overlap."""
    fx = await make_org(db)
    a = await _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id, fx["desk"].id,
                       berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 13))
    b = await _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id, fx["desk"].id,
                       berlin(2026, 10, 2, 12), berlin(2026, 10, 2, 17))
    assert a == "created"
    assert b == "taken"


async def test_adjacent_half_days_both_succeed(db, sessionmaker_factory):
    """tstzrange is half-open, so 09:00-13:00 and 13:00-17:00 do NOT overlap.
    Two people legitimately hold one desk on one day."""
    fx = await make_org(db)
    a = await _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id, fx["desk"].id,
                       berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 13))
    b = await _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id, fx["desk"].id,
                       berlin(2026, 10, 2, 13), berlin(2026, 10, 2, 17))
    assert (a, b) == ("created", "created")


async def test_cancelling_reopens_the_slot_with_no_row_deletion(db, sessionmaker_factory):
    """The partial predicate in the constraint is what makes this work."""
    fx = await make_org(db)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        b = await create_booking(s, repo, user_id=fx["user"].id, resource_id=fx["desk"].id,
                                 start=start, end=end, now=NOW)
        await s.commit()
        booking_id = b.id

    assert await _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id,
                          fx["desk"].id, start, end) == "taken"

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        from app.models import Booking
        held = await repo.get(Booking, booking_id)
        held.status = "cancelled"
        await s.commit()

    assert await _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id,
                          fx["desk"].id, start, end) == "created"

    # The cancelled row still exists -- no audit loss.
    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        from app.models import Booking
        assert (await repo.get(Booking, booking_id)).status == "cancelled"


async def test_completed_bookings_still_block(db, sessionmaker_factory):
    """'completed' is deliberately NOT a releasing status: a retroactive booking
    overlapping history would corrupt utilization data (TDD §4.1)."""
    fx = await make_org(db)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        b = await create_booking(s, repo, user_id=fx["user"].id, resource_id=fx["desk"].id,
                                 start=start, end=end, now=NOW)
        b.status = "completed"
        await s.commit()

    assert await _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id,
                          fx["desk"].id, start, end) == "taken"


async def test_capacity_counter_never_exceeds_its_cap_under_concurrency(
    db, sessionmaker_factory
):
    """TDD §16.2 variant -- proves the §4.2 locked counter holds."""
    CAP = 3
    fx = await make_org(db, capacity_cap=CAP, desks=10)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    results = await asyncio.gather(*[
        _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id, d.id, start, end)
        for d in fx["desks"]
    ])

    assert results.count("created") == CAP, results
    assert results.count("capacity") == 10 - CAP
