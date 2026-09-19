"""The canonical timezone rule. TDD §3.4.

A booking's day is the calendar date of its start instant in its SITE's timezone.
The device's timezone is never consulted. Every day-boundary computation in this
codebase goes through this module -- there is no second implementation.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo


def local_date_of(instant: datetime, site_timezone: str) -> date:
    """The site-local calendar date an instant falls on."""
    if instant.tzinfo is None:
        raise ValueError("naive datetime: all instants must be timezone-aware (TDD §3.1)")
    return instant.astimezone(ZoneInfo(site_timezone)).date()


def site_day_bounds(day: date, site_timezone: str, opens: time, closes: time) -> tuple[datetime, datetime]:
    """Opening and closing instants for a site-local day, as UTC-comparable datetimes."""
    tz = ZoneInfo(site_timezone)
    return (
        datetime.combine(day, opens, tzinfo=tz),
        datetime.combine(day, closes, tzinfo=tz),
    )


DEFAULT_OPEN = time(8, 0)
DEFAULT_CLOSE = time(18, 0)


def local_today(site_timezone: str, now: datetime | None = None) -> date:
    """Today, in the site's timezone. Never the server's."""

    return local_date_of(now or datetime.now(UTC), site_timezone)


def parse_opening_hours(opening_hours: dict | None) -> tuple[time, time]:
    """Site opening hours -> (opens, closes).

    The ONE place this parsing happens. It previously existed in both the
    booking service and the router, which is exactly the duplication §3.4 says
    not to have.
    """

    def one(value: object, fallback: time) -> time:
        if not isinstance(value, str):
            return fallback
        try:
            hh, mm = value.split(":")
            return time(int(hh), int(mm))
        except (ValueError, TypeError):
            return fallback

    hours = opening_hours or {}
    return one(hours.get("open"), DEFAULT_OPEN), one(hours.get("close"), DEFAULT_CLOSE)


def slot_bounds(
    day: date, site_timezone: str, opens: time, closes: time, slot: str
) -> tuple[datetime, datetime]:
    """Resolve a named slot (FR-2.2) against the site's own opening hours.

    A site opening at 07:00 gets sensible halves without the client hardcoding 09:00.
    """
    start, end = site_day_bounds(day, site_timezone, opens, closes)
    if slot == "day":
        return start, end
    midday = start + (end - start) / 2
    if slot == "am":
        return start, midday
    if slot == "pm":
        return midday, end
    raise ValueError(f"unknown slot {slot!r}; expected day|am|pm")
