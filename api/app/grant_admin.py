"""Grant an administrative role. FR-1.8, TDD §6.6.

THERE IS NO ENDPOINT THAT DOES THIS, deliberately: an endpoint that creates an
org admin is an endpoint that creates an org admin, and it would be reachable
by whoever found it first on a tenant that has none. So the founding grant on
a new tenant is an operator action, and this is it.

    uv run python -m app.grant_admin --list
    uv run python -m app.grant_admin priya@northwind.example org_admin
    uv run python -m app.grant_admin nadia@northwind.example site_admin --site Tampa

Against a remote database, the same way the README runs migrations:

    cd api && env $(grep -v '^#' .env.prod | xargs) \\
        uv run python -m app.grant_admin <email> org_admin --apply

THREE THINGS IT WILL NOT DO, each for a reason:

  - **It will not write anything without `--apply`.** Every run prints the
    host it is pointed at and exactly what it would do. A tool whose default
    is to mutate a production database is one you find out about afterwards.
  - **It will not invent a scope.** `site_admin` without a site that actually
    resolves is refused rather than stored as NULL, because a NULL scope reads
    as "admin of every office" -- the escalation revision 0004's CHECK exists
    to prevent. Failing before the database has to is the friendlier half of
    the same rule.
  - **It cannot revoke.** Removing the last org admin leaves an organization
    nobody can administer, and `PUT /admin/users/{id}/roles` refuses exactly
    that (`test_the_last_org_admin_cannot_be_demoted`). A CLI that could
    revoke would be a way around a rule the product enforces on purpose, so
    revocation stays in the console where the check lives.

Unlike `app.seed`, this does not refuse a remote host -- reaching one is the
whole point. It is additive and idempotent: nothing is deleted, and re-running
it is a no-op. That is the trade for not having the seed's `--yes` guard.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from urllib.parse import urlsplit

from sqlalchemy import text

from app.authz import ROLES
from app.config import settings
from app.db import SessionLocal, engine

#: Roles that name the thing they cover, as (table to look the name up in,
#: the scope_type the row carries). An org_admin grant is org-wide and takes
#: no scope; the other two are meaningless without one.
SCOPED = {
    "site_admin": ("site", "site"),
    "team_lead": ("user_group", "group"),
}


def target() -> str:
    """The database this run is pointed at, with the credentials removed."""
    parts = urlsplit(settings.database_url)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.hostname or '?'}{port}{parts.path}"


LIST_SQL = (
    "SELECT u.email, g.role, "
    "       coalesce(st.name, gr.name, '(org-wide)') AS scope "
    "FROM role_grant g "
    "JOIN app_user u ON u.id = g.user_id "
    "LEFT JOIN site st ON st.id = g.scope_id "
    "LEFT JOIN user_group gr ON gr.id = g.scope_id "
    "ORDER BY u.email, g.role"
)


async def show(s) -> int:
    rows = (await s.execute(text(LIST_SQL))).all()
    if not rows:
        print("  no grants -- nobody can open the admin console on this tenant")
        return 0
    for r in rows:
        print(f"  {r.email:<32} {r.role:<12} {r.scope}")
    return len(rows)


async def resolve_scope(s, organization_id, role: str, name: str | None):
    """The scope id this grant names.

    Returns (scope_id, error). An org grant resolves to None with no error; a
    scoped role with an unresolvable name is an error, never a None scope --
    see the module docstring.
    """
    scoped = SCOPED.get(role)
    if scoped is None:
        if name is not None:
            return None, f"{role} is org-wide and takes no --site/--team"
        return None, None

    table, _ = scoped
    if name is None:
        flag = "--site" if role == "site_admin" else "--team"
        return None, f"{role} names what it covers; pass {flag}"

    row = (
        await s.execute(
            text(
                # `table` comes from SCOPED, never from the command line.
                f"SELECT id FROM {table} "
                "WHERE organization_id = :org AND name = :name"
            ),
            {"org": organization_id, "name": name},
        )
    ).first()
    if row is None:
        return None, f"no {table.replace('_', ' ')} named {name!r} in that organization"
    return row.id, None


async def run(args) -> int:
    print(f"database: {target()}\n")

    async with SessionLocal() as s:
        if args.list:
            await show(s)
            return 0

        user = (
            await s.execute(
                text(
                    "SELECT id, organization_id, display_name, status "
                    "FROM app_user WHERE email = :email"
                ),
                {"email": args.email},
            )
        ).first()
        if user is None:
            print(f"no user {args.email}", file=sys.stderr)
            return 1
        if user.status != "active":
            # Granting a role to a deactivated account is almost always a
            # typo, and the silent version of it is a dormant admin.
            print(
                f"{args.email} is deactivated; reactivate them first", file=sys.stderr
            )
            return 1

        scope_id, why = await resolve_scope(
            s, user.organization_id, args.role, args.site or args.team
        )
        if why:
            print(f"refusing: {why}", file=sys.stderr)
            return 1

        already = (
            await s.execute(
                text(
                    "SELECT count(*) FROM role_grant WHERE user_id = :uid "
                    "AND role = :role AND scope_id IS NOT DISTINCT FROM :scope"
                ),
                {"uid": user.id, "role": args.role, "scope": scope_id},
            )
        ).scalar_one()

        where = args.site or args.team or "(org-wide)"
        if already:
            print(f"  HAVE  {user.display_name} is already {args.role} {where}")
            return 0

        print(f"  ADD   {user.display_name} <{args.email}>  {args.role}  {where}")
        if not args.apply:
            print("\nDRY RUN -- nothing written. Re-run with --apply.")
            return 0

        await s.execute(
            text(
                "INSERT INTO role_grant "
                "(organization_id, user_id, role, scope_type, scope_id) "
                "VALUES (:org, :uid, :role, :scope_type, :scope)"
            ),
            {
                "org": user.organization_id,
                "uid": user.id,
                "role": args.role,
                "scope_type": "org" if scope_id is None else SCOPED[args.role][1],
                "scope": scope_id,
            },
        )
        await s.commit()
        print("\ngrants now:")
        await show(s)
        return 0


def parse(argv: list[str] | None = None):
    p = argparse.ArgumentParser(
        prog="python -m app.grant_admin",
        description="Grant an administrative role (FR-1.8).",
    )
    p.add_argument("email", nargs="?", help="the person to grant it to")
    p.add_argument("role", nargs="?", choices=ROLES, help="the role to grant")
    p.add_argument("--site", help="site name, for site_admin")
    p.add_argument("--team", help="team name, for team_lead")
    p.add_argument("--list", action="store_true", help="show every grant and exit")
    p.add_argument("--apply", action="store_true", help="write it; otherwise a dry run")
    args = p.parse_args(argv)

    if not args.list and not (args.email and args.role):
        p.error("give an email and a role, or --list")
    if args.site and args.team:
        p.error("a grant covers a site or a team, not both")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    try:
        return asyncio.run(_with_engine(args))
    except KeyboardInterrupt:
        return 130


async def _with_engine(args) -> int:
    try:
        return await run(args)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
