"""FR-1.8 -- who may administer what.

No database. The decision is a pure function of the grants a user holds and
the scope of the thing they are touching, for the same reason the policy rules
are pure: a permission model you can only exercise through HTTP is one nobody
reads the edge cases of.
"""

import uuid

from app.authz import (
    ADMIN_ROLES,
    ROLES,
    Grant,
    administered_site_ids,
    administers_org,
    administers_site,
    is_admin,
)

TAMPA = uuid.uuid4()
BERLIN = uuid.uuid4()
DESIGN = uuid.uuid4()

EMPLOYEE: frozenset[Grant] = frozenset()
ORG_ADMIN = frozenset({Grant("org_admin", "org", None)})
TAMPA_ADMIN = frozenset({Grant("site_admin", "site", TAMPA)})
BOTH_SITES = frozenset(
    {Grant("site_admin", "site", TAMPA), Grant("site_admin", "site", BERLIN)}
)
TEAM_LEAD = frozenset({Grant("team_lead", "group", DESIGN)})


def test_holding_no_grant_is_being_an_employee():
    """The absence of a row is the employee role. There is nothing to read."""
    assert not is_admin(EMPLOYEE)
    assert not administers_org(EMPLOYEE)
    assert not administers_site(EMPLOYEE, TAMPA)


def test_an_org_admin_administers_every_site_including_ones_added_later():
    assert administers_org(ORG_ADMIN)
    assert administers_site(ORG_ADMIN, TAMPA)
    assert administers_site(ORG_ADMIN, uuid.uuid4())
    # None rather than a set: "every site" is not a list that has to be
    # recomputed the day someone adds one.
    assert administered_site_ids(ORG_ADMIN) is None


def test_a_site_admin_administers_exactly_their_own_site():
    assert administers_site(TAMPA_ADMIN, TAMPA)
    assert not administers_site(TAMPA_ADMIN, BERLIN)
    assert administered_site_ids(TAMPA_ADMIN) == {TAMPA}


def test_a_site_admin_is_not_an_org_admin():
    """The distinction the whole table exists for. A site admin runs an
    office; creating sites, people and roles stays org-wide, or the scoping
    is decorative."""
    assert is_admin(TAMPA_ADMIN)
    assert not administers_org(TAMPA_ADMIN)


def test_grants_are_additive():
    assert administered_site_ids(BOTH_SITES) == {TAMPA, BERLIN}
    assert administers_site(BOTH_SITES, TAMPA)
    assert administers_site(BOTH_SITES, BERLIN)


def test_a_team_lead_administers_nothing():
    """FR-5.8 is about anchor days, not about the workplace configuration.
    A lead who could edit floors would be a site admin with a nicer name."""
    assert not is_admin(TEAM_LEAD)
    assert not administers_org(TEAM_LEAD)
    assert not administers_site(TEAM_LEAD, TAMPA)
    assert administered_site_ids(TEAM_LEAD) == set()


def test_an_object_with_no_site_needs_an_org_admin():
    """`None` is "not attached to an office" -- a role grant, a group. A site
    admin must not reach it by holding a grant over some other site."""
    assert administers_site(ORG_ADMIN, None)
    assert not administers_site(TAMPA_ADMIN, None)
    assert not administers_site(BOTH_SITES, None)


def test_a_site_scoped_grant_cannot_be_widened_by_losing_its_scope():
    """A site_admin row with a NULL scope must never read as "every site".

    The database refuses to store one (the CHECK in revision 0004), and this
    asserts the in-memory half: if such a row ever did arrive -- from a bad
    backfill, or a migration written in a hurry -- it grants nothing rather
    than everything. Failing closed on the way in AND on the way out.
    """
    malformed = frozenset({Grant("site_admin", "site", None)})
    assert not administers_site(malformed, TAMPA)
    assert not administers_site(malformed, None)
    assert administered_site_ids(malformed) == set()


def test_employee_is_not_a_grantable_role():
    """It is the absence of a grant. A row saying `employee` would be a second
    way to express the same thing, and the two could disagree."""
    assert "employee" not in ROLES
    assert "employee" not in ADMIN_ROLES
    assert ADMIN_ROLES <= set(ROLES)
