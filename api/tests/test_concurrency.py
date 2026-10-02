"""TDD §16.2 -- the proof that §4.1 works.

This is the test the whole design rests on. It fires N genuinely concurrent
booking attempts at one desk and asserts exactly one wins. If a refactor ever
reintroduces a read-then-write race, this fails.
"""

import asyncio

from sqlalchemy import text

from app.booking_service import create_booking, with_booking_txn
from app.errors import CapacityExceeded, PolicyDenied, ResourceTaken
from app.models import Booking
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
        # The authoritative refusal: the locked counter, inside the
        # transaction (TDD §4.2). This is what concurrent callers hit.
        return "capacity"
    except PolicyDenied as denied:
        # The ADVISORY refusal, from rule_site_capacity. A caller arriving
        # after the count has already been committed is turned away by the
        # rule before it ever reaches the counter. Both mean "the site is
        # full"; which one fires is a question of timing, not of outcome,
        # so this test does not distinguish them.
        codes = [d["code"] for d in denied.extra.get("denials", [])]
        if "CAPACITY_EXCEEDED" in codes:
            return "capacity"
        # Like capacity, a second desk is refused by the rule or, under a
        # race, by the booking_one_desk_per_user constraint. Both raise this.
        return "second_desk" if "ALREADY_HAVE_DESK" in codes else "denied"


async def test_concurrent_bookings_on_one_desk_produce_exactly_one_winner(
    db, sessionmaker_factory
):
    # N different people. One person making N attempts would be refused by
    # rule_one_desk_per_user after the first commit, and prove nothing here.
    fx = await make_org(db, users=N)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    results = await asyncio.gather(*[
        _attempt(sessionmaker_factory, fx["org"].id, u.id, fx["desk"].id, start, end)
        for u in fx["users"]
    ])

    assert results.count("created") == 1, f"expected exactly one winner, got {results}"
    assert results.count("taken") == N - 1


async def test_overlapping_half_days_collide(db, sessionmaker_factory):
    """Half-day bookings are why the constraint ranges over time rather than
    keying on a date (TDD §4.4). 09:00-13:00 and 12:00-17:00 overlap."""
    fx = await make_org(db, users=2)
    first, other = fx["users"]
    a = await _attempt(sessionmaker_factory, fx["org"].id, first.id, fx["desk"].id,
                       berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 13))
    b = await _attempt(sessionmaker_factory, fx["org"].id, other.id, fx["desk"].id,
                       berlin(2026, 10, 2, 12), berlin(2026, 10, 2, 17))
    assert a == "created"
    assert b == "taken"


async def test_adjacent_half_days_both_succeed(db, sessionmaker_factory):
    """tstzrange is half-open, so 09:00-13:00 and 13:00-17:00 do NOT overlap.
    Two people legitimately hold one desk on one day."""
    fx = await make_org(db, users=2)
    first, other = fx["users"]
    a = await _attempt(sessionmaker_factory, fx["org"].id, first.id, fx["desk"].id,
                       berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 13))
    b = await _attempt(sessionmaker_factory, fx["org"].id, other.id, fx["desk"].id,
                       berlin(2026, 10, 2, 13), berlin(2026, 10, 2, 17))
    assert (a, b) == ("created", "created")


async def test_cancelling_reopens_the_slot_with_no_row_deletion(db, sessionmaker_factory):
    """The partial predicate in the constraint is what makes this work."""
    fx = await make_org(db, users=2)
    other = fx["users"][1]
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        b = await create_booking(s, repo, user_id=fx["user"].id, resource_id=fx["desk"].id,
                                 start=start, end=end, now=NOW)
        await s.commit()
        booking_id = b.id

    assert await _attempt(sessionmaker_factory, fx["org"].id, other.id,
                          fx["desk"].id, start, end) == "taken"

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        from app.models import Booking
        held = await repo.get(Booking, booking_id)
        held.status = "cancelled"
        await s.commit()

    assert await _attempt(sessionmaker_factory, fx["org"].id, other.id,
                          fx["desk"].id, start, end) == "created"

    # The cancelled row still exists -- no audit loss.
    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        from app.models import Booking
        assert (await repo.get(Booking, booking_id)).status == "cancelled"


async def test_completed_bookings_still_block(db, sessionmaker_factory):
    """'completed' is deliberately NOT a releasing status: a retroactive booking
    overlapping history would corrupt utilization data (TDD §4.1)."""
    fx = await make_org(db, users=2)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, fx["org"].id)
        b = await create_booking(s, repo, user_id=fx["user"].id, resource_id=fx["desk"].id,
                                 start=start, end=end, now=NOW)
        b.status = "completed"
        await s.commit()

    assert await _attempt(sessionmaker_factory, fx["org"].id, fx["users"][1].id,
                          fx["desk"].id, start, end) == "taken"


async def test_capacity_counter_never_exceeds_its_cap_under_concurrency(
    db, sessionmaker_factory
):
    """TDD §16.2 variant -- proves the §4.2 locked counter holds."""
    CAP = 3
    fx = await make_org(db, capacity_cap=CAP, desks=10, users=10)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    results = await asyncio.gather(*[
        _attempt(sessionmaker_factory, fx["org"].id, u.id, d.id, start, end)
        for u, d in zip(fx["users"], fx["desks"], strict=True)
    ])

    assert results.count("created") == CAP, results
    assert results.count("capacity") == 10 - CAP


async def test_cancelling_gives_the_days_capacity_back(db, sessionmaker_factory):
    """The counter is the thing that actually refuses the next booking, so a
    release that does not decrement it releases nothing.

    Until `release_booking` existed, `booked_count` only ever went up: a site
    with a cap (FR-6.3) lost a seat of capacity on every cancel-and-rebook
    cycle and eventually refused everyone while its desks sat empty. The
    booking row is still not deleted -- it flips to `cancelled`, and the
    exclusion constraint stops considering it (TDD §4.1).
    """
    from app.booking_service import release_booking

    CAP = 2
    fx = await make_org(db, capacity_cap=CAP, desks=5, users=5)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)
    org_id, users = fx["org"].id, fx["users"]

    filled = [
        await _attempt(sessionmaker_factory, org_id, u.id, d.id, start, end)
        for u, d in zip(users[:3], fx["desks"][:3], strict=True)
    ]
    assert filled == ["created", "created", "capacity"]

    # Cancel one, and the seat comes back -- once, not twice.
    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, org_id)
        booking = (await repo.list(Booking, Booking.status == "confirmed"))[0]
        assert await release_booking(s, booking) is True
        assert await release_booking(s, booking) is False
        await s.commit()

    assert await _attempt(
        sessionmaker_factory, org_id, users[3].id, fx["desks"][3].id, start, end
    ) == "created"
    assert await _attempt(
        sessionmaker_factory, org_id, users[4].id, fx["desks"][4].id, start, end
    ) == "capacity"


async def test_concurrent_cancellations_cannot_drive_the_counter_negative(
    db, sessionmaker_factory
):
    """A negative counter would hand out capacity that does not exist, which
    is the worse of the two ways to be wrong. The row is locked FOR UPDATE on
    the way down exactly as it is on the way up, and the value is floored."""
    from app.booking_service import release_booking

    fx = await make_org(db, capacity_cap=4, desks=4, users=4)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)
    org_id = fx["org"].id

    for u, d in zip(fx["users"], fx["desks"], strict=True):
        assert await _attempt(sessionmaker_factory, org_id, u.id, d.id, start, end) == "created"

    async def cancel_one(booking_id):
        async with sessionmaker_factory() as s:
            repo = TenantRepository(s, org_id)
            booking = await repo.get(Booking, booking_id)
            await release_booking(s, booking)
            await s.commit()

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, org_id)
        ids = [b.id for b in await repo.list(Booking)]

    await asyncio.gather(*[cancel_one(i) for i in ids])

    async with sessionmaker_factory() as s:
        count = (
            await s.execute(
                text(
                    "SELECT booked_count FROM site_day_capacity "
                    "WHERE site_id = :site AND local_date = :d"
                ),
                {"site": fx["site"].id, "d": start.date()},
            )
        ).scalar()
    assert count == 0


# ---------------------------------------------------------------------------
# One desk per person at a time (booking_one_desk_per_user, migration 0005).
# The mirror of the test above: there, many people race for one desk; here,
# one person races for many desks. Without the constraint, every attempt sees
# no existing booking in its policy check and every one of them wins.
# ---------------------------------------------------------------------------


async def test_one_person_racing_for_many_desks_gets_exactly_one(db, sessionmaker_factory):
    fx = await make_org(db, desks=N)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    results = await asyncio.gather(*[
        _attempt(sessionmaker_factory, fx["org"].id, fx["user"].id, d.id, start, end)
        for d in fx["desks"]
    ])

    assert results.count("created") == 1, f"expected exactly one desk, got {results}"
    assert results.count("second_desk") == N - 1, results


async def test_a_second_desk_the_same_day_is_refused(db, sessionmaker_factory):
    """The reported bug: 5F-N-03 then 5F-N-04 for the same day, both confirmed."""
    fx = await make_org(db, desks=2)
    org, user = fx["org"].id, fx["user"].id
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)
    assert await _attempt(sessionmaker_factory, org, user, fx["desks"][0].id, start, end) == "created"
    assert await _attempt(
        sessionmaker_factory, org, user, fx["desks"][1].id, start, end
    ) == "second_desk"


async def test_the_constraint_holds_without_the_rule(db, sessionmaker_factory):
    """The policy rule is advisory. Insert past it -- as a concurrent request
    effectively does -- and the schema still refuses the row."""
    from sqlalchemy.dialects.postgresql import Range
    from sqlalchemy.exc import IntegrityError

    fx = await make_org(db, desks=2)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)

    def row(desk):
        return Booking(
            organization_id=fx["org"].id, site_id=fx["site"].id, resource_id=desk.id,
            user_id=fx["user"].id, during=Range(start, end, bounds="[)"),
            local_date=start.date(), status="confirmed", created_by=fx["user"].id,
        )

    async with sessionmaker_factory() as s:
        s.add(row(fx["desks"][0]))
        await s.commit()
    async with sessionmaker_factory() as s:
        s.add(row(fx["desks"][1]))
        try:
            await s.commit()
        except IntegrityError as exc:
            assert "booking_one_desk_per_user" in str(exc)
        else:
            raise AssertionError("a second overlapping desk was stored")


async def test_morning_at_one_desk_afternoon_at_another(db, sessionmaker_factory):
    """Overlap, not date (TDD §4.4): am and pm are a legitimate day on two desks."""
    fx = await make_org(db, desks=2)
    org, user = fx["org"].id, fx["user"].id
    am = await _attempt(sessionmaker_factory, org, user, fx["desks"][0].id,
                        berlin(2026, 10, 2, 8), berlin(2026, 10, 2, 13))
    pm = await _attempt(sessionmaker_factory, org, user, fx["desks"][1].id,
                        berlin(2026, 10, 2, 13), berlin(2026, 10, 2, 18))
    assert (am, pm) == ("created", "created")


async def test_a_whole_day_overlaps_either_half(db, sessionmaker_factory):
    fx = await make_org(db, desks=2)
    org, user = fx["org"].id, fx["user"].id
    assert await _attempt(sessionmaker_factory, org, user, fx["desks"][0].id,
                          berlin(2026, 10, 2, 13), berlin(2026, 10, 2, 18)) == "created"
    assert await _attempt(sessionmaker_factory, org, user, fx["desks"][1].id,
                          berlin(2026, 10, 2, 8), berlin(2026, 10, 2, 18)) == "second_desk"


async def test_a_desk_on_another_day_is_fine(db, sessionmaker_factory):
    fx = await make_org(db, desks=2)
    org, user = fx["org"].id, fx["user"].id
    assert await _attempt(sessionmaker_factory, org, user, fx["desks"][0].id,
                          berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)) == "created"
    assert await _attempt(sessionmaker_factory, org, user, fx["desks"][1].id,
                          berlin(2026, 10, 5, 9), berlin(2026, 10, 5, 17)) == "created"


async def test_a_room_alongside_a_desk_is_fine(db, sessionmaker_factory):
    """A room is a meeting, not a seat (TDD §7.1)."""
    fx = await make_org(db, desks=1, rooms=2)
    org, user = fx["org"].id, fx["user"].id
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)
    assert await _attempt(sessionmaker_factory, org, user, fx["desk"].id, start, end) == "created"
    assert await _attempt(sessionmaker_factory, org, user, fx["rooms"][0].id,
                          berlin(2026, 10, 2, 10), berlin(2026, 10, 2, 11)) == "created"
    # Nor does one room limit another: back-to-back meetings may overlap a
    # little, and a person is not occupying either.
    assert await _attempt(sessionmaker_factory, org, user, fx["rooms"][1].id,
                          berlin(2026, 10, 2, 10), berlin(2026, 10, 2, 12)) == "created"


async def test_cancelling_your_desk_lets_you_book_another(db, sessionmaker_factory):
    from app.booking_service import release_booking

    fx = await make_org(db, desks=2)
    org, user = fx["org"].id, fx["user"].id
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)
    assert await _attempt(sessionmaker_factory, org, user, fx["desks"][0].id, start, end) == "created"

    async with sessionmaker_factory() as s:
        repo = TenantRepository(s, org)
        await release_booking(s, (await repo.list(Booking))[0])
        await s.commit()

    assert await _attempt(sessionmaker_factory, org, user, fx["desks"][1].id, start, end) == "created"


async def test_two_people_on_two_desks_are_unaffected(db, sessionmaker_factory):
    fx = await make_org(db, desks=2, users=2)
    start, end = berlin(2026, 10, 2, 9), berlin(2026, 10, 2, 17)
    results = await asyncio.gather(*[
        _attempt(sessionmaker_factory, fx["org"].id, u.id, d.id, start, end)
        for u, d in zip(fx["users"], fx["desks"], strict=True)
    ])
    assert results == ["created", "created"]
