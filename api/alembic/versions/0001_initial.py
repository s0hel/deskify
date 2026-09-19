"""Initial schema, including the exclusion constraint that makes FR-2.13 structural.

Revision ID: 0001
Revises:
"""

from alembic import op
from app.models import Base

#: Frozen at this revision. Do not add to this list -- new tables belong to a
#: new migration.
TABLES_AT_0001 = (
    "organization",
    "email_domain",
    "app_user",
    "site",
    "floor",
    "zone",
    "resource",
    "booking",
    "site_day_capacity",
    "policy",
    "idempotency_key",
    "job",
    "day_declaration",
    "audit_log",
)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # btree_gist gives us uuid equality inside a GiST index, which the
    # exclusion constraint below needs for `resource_id WITH =`.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # ONLY the tables that existed at this revision.
    #
    # `Base.metadata.create_all()` with no argument creates whatever the models
    # look like TODAY, which makes this migration a moving target rather than a
    # snapshot: add a table to models.py and this revision silently starts
    # creating it, then the later revision that is supposed to create it fails
    # with "relation already exists" -- but only on a fresh database, so the
    # existing dev box never notices. Found by deploying (see §14.5).
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES_AT_0001],
    )

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
    bind = op.get_bind()
    Base.metadata.drop_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in TABLES_AT_0001],
    )
