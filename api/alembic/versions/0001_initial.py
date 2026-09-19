"""Initial schema, including the exclusion constraint that makes FR-2.13 structural.

Revision ID: 0001
Revises:
"""

from alembic import op
from app.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # btree_gist gives us uuid equality inside a GiST index, which the
    # exclusion constraint below needs for `resource_id WITH =`.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    # ------------------------------------------------------------------
    # TDD §4.1 -- the load-bearing decision of the entire design.
    #
    # Two overlapping live bookings on one resource are not rejected by
    # application code; they are impossible to store. The partial predicate
    # is what makes cancellation work: a cancelled booking stops
    # participating and its slot reopens with no row deletion.
    #
    # 'completed' deliberately REMAINS in the constraint. A completed booking
    # is history, but letting a new booking overlap it would corrupt
    # utilization data retroactively.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE booking ADD CONSTRAINT booking_no_double_allocation
            EXCLUDE USING gist (
                resource_id WITH =,
                during      WITH &&
            ) WHERE (status NOT IN ('cancelled','released_no_show'))
        """
    )

    op.execute(
        """
        CREATE INDEX booking_site_day ON booking (site_id, local_date)
            WHERE status NOT IN ('cancelled','released_no_show')
        """
    )
    op.execute("CREATE INDEX booking_user_upcoming ON booking (user_id, local_date DESC)")
    op.execute(
        "CREATE INDEX booking_sweep ON booking (status, local_date) WHERE status = 'confirmed'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE booking DROP CONSTRAINT IF EXISTS booking_no_double_allocation")
    Base.metadata.drop_all(bind=op.get_bind())
