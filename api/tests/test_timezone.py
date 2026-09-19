"""TDD §3.4 -- the one canonical day-boundary rule.

"A booking's day is the calendar date of its start instant in its SITE's
timezone. The device's timezone is never consulted."

These are the cases that make that rule earn its keep.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.timezone import local_date_of, parse_opening_hours, slot_bounds

BERLIN = "Europe/Berlin"
LA = "America/Los_Angeles"


def test_local_date_uses_the_site_not_utc():
    """23:30 UTC on 1 Oct is already 2 Oct in Berlin."""
    instant = datetime(2026, 10, 1, 23, 30, tzinfo=UTC)
    assert local_date_of(instant, BERLIN) == date(2026, 10, 2)


def test_local_date_differs_between_two_sites_for_one_instant():
    """A user with bookings at two sites can legitimately have two 'todays'."""
    instant = datetime(2026, 10, 2, 3, 0, tzinfo=UTC)
    assert local_date_of(instant, BERLIN) == date(2026, 10, 2)
    assert local_date_of(instant, LA) == date(2026, 10, 1)


def test_naive_datetimes_are_refused_loudly():
    """A naive datetime here would silently assume the server's timezone."""
    with pytest.raises(ValueError, match="naive"):
        # DTZ001 is the point of this test: the naive datetime is deliberate.
        local_date_of(datetime(2026, 10, 1, 9, 0), BERLIN)  # noqa: DTZ001


def test_day_boundary_across_a_dst_transition():
    """Europe/Berlin leaves DST on 25 Oct 2026. 00:30 UTC that day is 02:30
    local, still the 25th -- the date must not slip."""
    instant = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert local_date_of(instant, BERLIN) == date(2026, 10, 25)


def test_slot_bounds_derive_halves_from_the_sites_own_hours():
    """FR-2.2 -- a site opening at 07:00 gets sensible halves without the
    client hardcoding 09:00."""
    day = date(2026, 10, 2)
    start, end = slot_bounds(day, BERLIN, time(7, 0), time(19, 0), "day")
    assert start.astimezone(ZoneInfo(BERLIN)).hour == 7
    assert end.astimezone(ZoneInfo(BERLIN)).hour == 19

    am_start, am_end = slot_bounds(day, BERLIN, time(7, 0), time(19, 0), "am")
    pm_start, pm_end = slot_bounds(day, BERLIN, time(7, 0), time(19, 0), "pm")
    assert am_start == start and pm_end == end
    assert am_end == pm_start == start + (end - start) / 2
    assert am_end.astimezone(ZoneInfo(BERLIN)).hour == 13


def test_adjacent_slots_share_a_boundary_so_they_do_not_overlap():
    """With half-open '[)' ranges this is what lets two people hold one desk
    on one day (TDD §4.4)."""
    day = date(2026, 10, 2)
    _, am_end = slot_bounds(day, BERLIN, time(8, 0), time(18, 0), "am")
    pm_start, _ = slot_bounds(day, BERLIN, time(8, 0), time(18, 0), "pm")
    assert am_end == pm_start


def test_unknown_slot_is_refused():
    with pytest.raises(ValueError, match="unknown slot"):
        slot_bounds(date(2026, 10, 2), BERLIN, time(8), time(18), "evening")


@pytest.mark.parametrize(
    "hours,expected",
    [
        ({"open": "07:30", "close": "19:45"}, (time(7, 30), time(19, 45))),
        (None, (time(8, 0), time(18, 0))),
        ({}, (time(8, 0), time(18, 0))),
        ({"open": "nonsense", "close": "19:00"}, (time(8, 0), time(19, 0))),
        ({"open": 700, "close": None}, (time(8, 0), time(18, 0))),
    ],
)
def test_opening_hours_parsing_falls_back_rather_than_crashing(hours, expected):
    """Bad data from a CSV import must not take the booking path down."""
    assert parse_opening_hours(hours) == expected
