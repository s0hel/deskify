"""Role grants. FR-1.8, TDD §6.6.

Columns are spelled out rather than taken from the models, so this revision
keeps describing the schema as it was HERE even after the models move on.

A grant is additive: holding none makes you an employee, which is why there is
no role column on app_user and no row to write when someone joins. The unique
constraint treats a NULL scope_id as org-wide, and Postgres does not consider
two NULLs equal in a unique index -- hence the two partial indexes rather than
one UniqueConstraint, which would happily store the same org-wide grant twice.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_grant",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('team_lead','site_admin','org_admin')", name="role_grant_role_check"
        ),
        sa.CheckConstraint(
            "scope_type IN ('org','site','group')", name="role_grant_scope_check"
        ),
        # An org-scoped grant has no scope_id and a narrower one must have one.
        # Without this a site_admin row with a NULL site would read as "admin of
        # every site", which is the privilege escalation this table exists to
        # make impossible to write by accident.
        sa.CheckConstraint(
            "(scope_type = 'org') = (scope_id IS NULL)", name="role_grant_scope_id_check"
        ),
    )
    op.create_index("ix_role_grant_organization_id", "role_grant", ["organization_id"])
    # The one lookup that happens on every authenticated admin request.
    op.create_index("role_grant_user", "role_grant", ["organization_id", "user_id"])
    op.create_index(
        "role_grant_unique_scoped",
        "role_grant",
        ["organization_id", "user_id", "role", "scope_id"],
        unique=True,
        postgresql_where=sa.text("scope_id IS NOT NULL"),
    )
    op.create_index(
        "role_grant_unique_org",
        "role_grant",
        ["organization_id", "user_id", "role"],
        unique=True,
        postgresql_where=sa.text("scope_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("role_grant")
