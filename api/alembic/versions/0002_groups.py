"""Teams and group membership.

Columns are spelled out rather than taken from the models, so this revision
keeps describing the schema as it was HERE even after the models move on.
Revision 0003 adds user_group.anchor_days; this one must not.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_group",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="team"),
        sa.UniqueConstraint("organization_id", "name", name="user_group_org_name_key"),
        sa.CheckConstraint(
            "kind IN ('team','department','custom')", name="user_group_kind_check"
        ),
    )
    op.create_index("ix_user_group_organization_id", "user_group", ["organization_id"])

    op.create_table(
        "group_member",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_group.id"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id"),
            primary_key=True,
        ),
    )
    op.create_index("ix_group_member_organization_id", "group_member", ["organization_id"])
    # The "who's in" query joins membership to itself to find shared groups,
    # so the reverse lookup needs to be indexed too.
    op.create_index("group_member_user", "group_member", ["user_id"])


def downgrade() -> None:
    op.drop_table("group_member")
    op.drop_table("user_group")
