"""Team anchor days.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_group ADD COLUMN anchor_days jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_group DROP COLUMN anchor_days")
