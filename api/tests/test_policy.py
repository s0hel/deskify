"""TDD §16.1 -- rules are pure, so test them exhaustively. No database."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app.policy import PolicyContext, evaluate

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def ctx(**over) -> PolicyContext:
    start = over.pop("start", datetime(2026, 10, 2, 9, 0, tzinfo=TZ))
    end = over.pop("end", datetime(2026, 10, 2, 17, 0, tzinfo=TZ))
    base = {
        "now": NOW,
        "requested_start": start,
        "requested_end": end,
        "local_date": start.date(),
        "site_timezone": "Europe/Berlin",
        "site_opens": time(8, 0),
        "site_closes": time(18, 0),
    }
    base.update(over)
    return PolicyContext(**base)


def codes(c) -> list[str]:
    return [d.code for d in evaluate(c)]


def test_clean_booking_is_allowed():
    assert codes(ctx()) == []


def test_booking_horizon(   ):
    c = ctx(start=datetime(2026, 11, 30, 9, tzinfo=TZ), end=datetime(2026, 11, 30, 17, tzinfo=TZ),
            rules={"booking_horizon_days": 14})
    assert "BOOKING_HORIZON_EXCEEDED" in codes(c)


def test_horizon_inside_limit_passes():
    c = ctx(rules={"booking_horizon_days": 14})
    assert codes(c) == []


def test_max_future_bookings():
    c = ctx(rules={"max_future_bookings": 3}, user_future_booking_count=3)
    assert "MAX_FUTURE_BOOKINGS" in codes(c)


def test_outside_opening_hours():
    c = ctx(end=datetime(2026, 10, 2, 19, 0, tzinfo=TZ))
    assert "OUTSIDE_OPENING_HOURS" in codes(c)


def test_out_of_service_desk():
    assert "RESOURCE_UNAVAILABLE" in codes(ctx(resource_status="out_of_service"))


def test_zone_restricted_to_a_group_the_user_is_not_in():
    assert "ZONE_RESTRICTED" in codes(ctx(zone_restricted_to_group_id="g1", user_group_ids=()))


def test_zone_restriction_passes_for_a_member():
    assert codes(ctx(zone_restricted_to_group_id="g1", user_group_ids=("g1",))) == []


def test_assigned_desk_blocks_others():
    assert "DESK_ASSIGNED" in codes(ctx(resource_assigned_user_id="owner", user_id="someone"))


def test_assigned_desk_allows_its_owner():
    assert codes(ctx(resource_assigned_user_id="me", user_id="me")) == []


def test_assigned_desk_opens_when_owner_declares_away():
    """FR-6.7 via the day_declaration table."""
    c = ctx(resource_assigned_user_id="owner", user_id="someone", assigned_owner_is_away=True)
    assert codes(c) == []


def test_blackout():
    assert "SITE_CLOSED" in codes(ctx(blackout_reason="Maintenance"))


def test_all_denials_are_returned_not_just_the_first():
    """FR-6.9 -- a UI that fixes one refusal only to hit the next is what this prevents."""
    c = ctx(
        start=datetime(2026, 11, 30, 7, 0, tzinfo=TZ),
        end=datetime(2026, 11, 30, 19, 0, tzinfo=TZ),
        rules={"booking_horizon_days": 14, "max_future_bookings": 1},
        user_future_booking_count=5, resource_status="out_of_service",
    )
    got = codes(c)
    assert len(got) >= 4
    assert "OUTSIDE_OPENING_HOURS" in got and "BOOKING_HORIZON_EXCEEDED" in got


def test_denial_order_is_deterministic():
    c = ctx(blackout_reason="Closed", resource_status="out_of_service",
            rules={"booking_horizon_days": 0})
    assert codes(c)[0] == "SITE_CLOSED"


def test_denials_carry_params_for_client_side_localization():
    """FR-10.4 -- the client builds the message from code + params."""
    d = evaluate(ctx(rules={"booking_horizon_days": 14},
                     start=datetime(2026, 12, 1, 9, tzinfo=TZ),
                     end=datetime(2026, 12, 1, 17, tzinfo=TZ)))[0]
    assert d.params["limit_days"] == 14
    assert d.rule_key == "booking_horizon_days"


# --------------------------------------------------------------------------
# The administrative override (FR-8.6)
# --------------------------------------------------------------------------


def overridden(c) -> list[str]:
    return [d.code for d in evaluate(c, override=True)]


def test_an_override_drops_the_configurable_limits():
    """The horizon and the concurrent-booking cap are preferences about how
    employees should behave. An admin fixing something for a colleague should
    not have to argue with them."""
    c = ctx(
        start=datetime(2026, 11, 30, 9, tzinfo=TZ),
        end=datetime(2026, 11, 30, 17, tzinfo=TZ),
        rules={"booking_horizon_days": 14, "max_future_bookings": 1},
        user_future_booking_count=3,
    )
    assert sorted(codes(c)) == ["BOOKING_HORIZON_EXCEEDED", "MAX_FUTURE_BOOKINGS"]
    assert overridden(c) == []


def test_an_override_drops_a_zone_restriction():
    c = ctx(zone_restricted_to_group_id="design", user_group_ids=())
    assert codes(c) == ["ZONE_RESTRICTED"]
    assert overridden(c) == []


def test_an_override_does_not_reopen_a_closed_building():
    """Blackouts and opening hours describe the BUILDING. Overriding them
    books a desk nobody can reach."""
    shut = ctx(blackout_reason="Floor resurfacing")
    after_hours = ctx(
        start=datetime(2026, 10, 2, 5, tzinfo=TZ), end=datetime(2026, 10, 2, 7, tzinfo=TZ)
    )
    assert overridden(shut) == codes(shut) != []
    assert overridden(after_hours) == codes(after_hours) != []


def test_an_override_does_not_resurrect_a_broken_desk():
    """An admin took it out of service on purpose, usually themselves."""
    c = ctx(resource_status="out_of_service")
    assert overridden(c) == codes(c) == ["RESOURCE_UNAVAILABLE"]


def test_an_override_does_not_give_away_someone_elses_assigned_desk():
    """FR-6.7. That is not an override, it is a different decision."""
    c = ctx(resource_assigned_user_id="ren", user_id="dana")
    assert overridden(c) == codes(c) == ["DESK_ASSIGNED"]


def test_an_override_does_not_break_the_site_capacity_cap():
    """FR-6.3 is a HARD limit -- often a fire-safety or works-council number
    rather than a preference. Overriding it here would also be a lie: the
    authoritative check is the locked counter inside the booking transaction
    (TDD §4.2), which a pure rule cannot reach."""
    c = ctx(site_capacity_cap=10, site_booked_count=10)
    assert overridden(c) == codes(c) == ["CAPACITY_EXCEEDED"]


def test_the_overridable_set_is_a_subset_of_the_rules_that_run():
    """A rule renamed or reordered out of RULES must not leave a dangling
    entry here that silently overrides nothing."""
    from app.policy import OVERRIDABLE_RULES, RULES

    assert set(OVERRIDABLE_RULES) < set(RULES)
