"""Who may see whose presence. FR-5.6, and the answer to PRD Q6.

This module is the ONLY place the visibility rule is expressed. Every endpoint
that can reveal where or when a named person is in the office goes through
`visible_user_ids`, and the filter is applied in the QUERY rather than the
serializer -- a person set to `nobody` must not appear in a result set at all,
because filtering afterwards is how presence leaks into counts, pagination
totals and debug logs (TDD §5.2).

Presence data is data about where a named employee physically is. PRD §9.4 is
explicit that this makes the product more privacy-sensitive than its feature
list suggests, and European works councils will require both the per-user
opt-out and the org-level kill switch implemented here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, and_, exists, or_, select

from app.models import AppUser, GroupMember, Organization

# ---------------------------------------------------------------------------
# A NOTE FOR WHOEVER BUILDS FR-5.7 (find a colleague on the floor plan).
#
# The UI promises that "Nobody" means you will not appear in anyone's team view
# OR ON THE PLAN. Today `/floors/{id}/state` returns only free/booked/mine and
# carries no identity, so that promise holds. The moment the plan shows who is
# sitting where -- initials, avatars, a "sit near" marker -- that endpoint must
# filter through `visible_user_ids` as well, or the app will be lying in a
# sentence a works council has read.
# ---------------------------------------------------------------------------

#: Per-user setting (FR-5.6).
VISIBILITY_EVERYONE = "everyone"
VISIBILITY_TEAM = "team"
VISIBILITY_NOBODY = "nobody"

#: Org-level master switch (PRD §5.3, Q6). Absent means enabled.
PRESENCE_ENABLED_KEY = "presence_enabled"


def presence_enabled(org: Organization) -> bool:
    """The org-wide kill switch. Defaults to on; an explicit false turns every
    colleague view into just the viewer."""
    return bool((org.settings or {}).get(PRESENCE_ENABLED_KEY, True))


def shares_a_group_with(user_column, viewer_id: uuid.UUID):
    """EXISTS a group that both `user_column` and the viewer belong to."""
    mine = GroupMember.__table__.alias("gm_viewer")
    theirs = GroupMember.__table__.alias("gm_subject")
    return exists(
        select(1).where(
            and_(
                theirs.c.user_id == user_column,
                mine.c.user_id == viewer_id,
                theirs.c.group_id == mine.c.group_id,
            )
        )
    )


def visible_user_ids(
    organization_id: uuid.UUID,
    viewer_id: uuid.UUID,
    *,
    org_presence_enabled: bool = True,
) -> Select:
    """A SELECT of the user ids whose presence `viewer_id` may see.

    Use it as `Model.user_id.in_(visible_user_ids(...))` so the restriction is
    part of the query plan, not a post-filter.

    You can always see yourself: the setting governs what OTHERS see, and a
    person who has hidden their days must still be shown their own.
    """
    conditions = [AppUser.id == viewer_id]

    if org_presence_enabled:
        conditions.append(
            or_(
                AppUser.presence_visibility == VISIBILITY_EVERYONE,
                and_(
                    AppUser.presence_visibility == VISIBILITY_TEAM,
                    shares_a_group_with(AppUser.id, viewer_id),
                ),
            )
        )

    return select(AppUser.id).where(
        AppUser.organization_id == organization_id,
        AppUser.status == "active",
        or_(*conditions),
    )
