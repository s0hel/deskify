"""The policy engine. TDD §4.3.

Rules are PURE FUNCTIONS over a PolicyContext loaded once per request. No rule
performs I/O. That is what makes the engine unit-testable without a database
(TDD §16.1) and makes the /bookings/validate dry run free.

All rules are evaluated -- never short-circuited -- because a UI that fixes one
refusal only to hit the next is the experience FR-6.9 exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Denial:
    code: str
    rule_key: str
    scope: str
    params: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "rule_key": self.rule_key,
            "scope": self.scope,
            "params": self.params,
        }


@dataclass
class PolicyContext:
    """Everything the rules need, loaded once. No rule reaches past this."""

    now: datetime
    requested_start: datetime
    requested_end: datetime
    local_date: date
    site_timezone: str
    site_opens: time
    site_closes: time
    # resolved policy values, most specific scope already applied
    rules: dict[str, object] = field(default_factory=dict)
    rule_scopes: dict[str, str] = field(default_factory=dict)
    user_future_booking_count: int = 0
    resource_status: str = "active"
    resource_assigned_user_id: str | None = None
    user_id: str | None = None
    zone_restricted_to_group_id: str | None = None
    user_group_ids: tuple[str, ...] = ()
    assigned_owner_is_away: bool = False
    blackout_reason: str | None = None
    site_booked_count: int = 0
    site_capacity_cap: int | None = None

    def scope_of(self, key: str) -> str:
        return self.rule_scopes.get(key, "org")


Rule = "Callable[[PolicyContext], Denial | None]"


def rule_blackout(ctx: PolicyContext) -> Denial | None:
    """FR-6.5."""
    if ctx.blackout_reason:
        return Denial(
            "SITE_CLOSED", "blackout", "site", {"reason": ctx.blackout_reason,
                                                "date": ctx.local_date.isoformat()}
        )
    return None


def rule_opening_hours(ctx: PolicyContext) -> Denial | None:
    """Compared in SITE time, never the device's. TDD §3.4."""
    tz = ZoneInfo(ctx.site_timezone)
    start_t = ctx.requested_start.astimezone(tz).time()
    end_t = ctx.requested_end.astimezone(tz).time()
    if start_t < ctx.site_opens or end_t > ctx.site_closes:
        return Denial(
            "OUTSIDE_OPENING_HOURS",
            "opening_hours",
            "site",
            {"opens": ctx.site_opens.isoformat(), "closes": ctx.site_closes.isoformat()},
        )
    return None


def rule_resource_available(ctx: PolicyContext) -> Denial | None:
    """FR-8.6 -- a desk taken out of service is not bookable."""
    if ctx.resource_status != "active":
        return Denial("RESOURCE_UNAVAILABLE", "resource_status", "site",
                      {"status": ctx.resource_status})
    return None


def rule_booking_horizon(ctx: PolicyContext) -> Denial | None:
    """FR-6.1."""
    limit = ctx.rules.get("booking_horizon_days")
    if limit is None:
        return None
    days_ahead = (ctx.local_date - ctx.now.date()).days
    if days_ahead > int(limit):
        return Denial(
            "BOOKING_HORIZON_EXCEEDED",
            "booking_horizon_days",
            ctx.scope_of("booking_horizon_days"),
            {"limit_days": int(limit), "requested_days_ahead": days_ahead},
        )
    return None


def rule_max_concurrent(ctx: PolicyContext) -> Denial | None:
    """FR-6.2."""
    limit = ctx.rules.get("max_future_bookings")
    if limit is None:
        return None
    if ctx.user_future_booking_count >= int(limit):
        return Denial(
            "MAX_FUTURE_BOOKINGS",
            "max_future_bookings",
            ctx.scope_of("max_future_bookings"),
            {"limit": int(limit), "current": ctx.user_future_booking_count},
        )
    return None


def rule_zone_permission(ctx: PolicyContext) -> Denial | None:
    """FR-6.4."""
    required = ctx.zone_restricted_to_group_id
    if required and required not in ctx.user_group_ids:
        return Denial("ZONE_RESTRICTED", "zone_permission", "site", {"group_id": required})
    return None


def rule_assigned_desk(ctx: PolicyContext) -> Denial | None:
    """FR-6.7 -- an assigned desk is bookable by its owner, or by anyone on a
    day the owner has declared away."""
    owner = ctx.resource_assigned_user_id
    if owner is None or owner == ctx.user_id:
        return None
    if ctx.assigned_owner_is_away:
        return None
    return Denial("DESK_ASSIGNED", "assigned_desk", "site", {"owner_user_id": owner})


def rule_site_capacity(ctx: PolicyContext) -> Denial | None:
    """FR-6.3 -- advisory here; the authoritative check is the locked counter
    in the booking transaction (TDD §4.2). This exists so /bookings/validate
    can warn before the user commits."""
    cap = ctx.site_capacity_cap
    if cap is None:
        return None
    if ctx.site_booked_count >= cap:
        return Denial("CAPACITY_EXCEEDED", "site_capacity_cap", "site",
                      {"cap": cap, "booked": ctx.site_booked_count})
    return None


#: Fixed, declared order so the "first" denial a client shows is deterministic:
#: cheapest and most comprehensible refusals first, policy limits after.
RULES: tuple = (
    rule_blackout,
    rule_opening_hours,
    rule_resource_available,
    rule_zone_permission,
    rule_assigned_desk,
    rule_site_capacity,
    rule_booking_horizon,
    rule_max_concurrent,
)


#: The rules an administrator may set aside (FR-8.6). Naming them here, as a
#: set, is what keeps "override" from meaning "skip the checks": everything
#: absent from this tuple stays in force for an admin.
#:
#: What is deliberately NOT overridable, and why:
#:   - `rule_blackout` and `rule_opening_hours` describe the BUILDING. The
#:     office is shut; an override would book a desk nobody can reach.
#:   - `rule_resource_available` is a desk that is broken or gone. An admin
#:     took it out of service on purpose, usually themselves.
#:   - `rule_assigned_desk` is somebody's own desk (FR-6.7). Giving it away
#:     over their head is not an override, it is a different decision.
#:   - `rule_site_capacity` is a HARD limit (FR-6.3), often a fire-safety or
#:     works-council number rather than a preference. Overriding it here
#:     would also be a lie: the authoritative check is the locked counter in
#:     the booking transaction (TDD §4.2), which this cannot reach.
#:
#: What remains is the three genuinely configurable limits -- how far ahead,
#: how many at once, and who may use a zone.
OVERRIDABLE_RULES: tuple = (
    rule_zone_permission,
    rule_booking_horizon,
    rule_max_concurrent,
)


def evaluate(ctx: PolicyContext, *, override: bool = False) -> list[Denial]:
    """Run every rule. Returns all denials, in declared order.

    `override` is FR-8.6's administrative override and drops exactly the rules
    in OVERRIDABLE_RULES. It is a parameter of the pure function rather than a
    branch in the caller so that the set of rules an admin can set aside is
    stated in one readable place and tested without a database.
    """
    rules = tuple(r for r in RULES if not (override and r in OVERRIDABLE_RULES))
    return [d for d in (rule(ctx) for rule in rules) if d is not None]
