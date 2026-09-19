"""Teams and group membership.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
from app.models import GroupMember, UserGroup

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    UserGroup.__table__.create(bind)
    GroupMember.__table__.create(bind)
    # The "who's in" query joins membership to itself to find shared groups,
    # so the reverse lookup needs to be indexed too.
    op.execute("CREATE INDEX group_member_user ON group_member (user_id)")


def downgrade() -> None:
    bind = op.get_bind()
    GroupMember.__table__.drop(bind)
    UserGroup.__table__.drop(bind)
