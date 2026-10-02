"""One desk per person at a time. TDD §4.1, §4.4.

`booking_no_double_allocation` stops two people taking one desk. Nothing
stopped one person taking two: a client that skipped the web app's UI (the
Teams bot, a script) could hold 5F-N-03 and 5F-N-04 for the same day, both
confirmed, and the second desk sat empty while counting against the site.

This is the mirror image of the existing constraint, and it is enforced the
same way -- in the schema, not by a read-then-write in application code -- so
that two concurrent requests from one person cannot both slip past a check.

It ranges over TIME, not over local_date, for the reason §4.4 gives for the
original: half-days. A morning at one desk and an afternoon at another is a
legitimate day; `&&` on half-open ranges permits it with no extra logic.

It covers DESKS only. A room is a meeting, not a seat (TDD §7.1): someone who
holds a desk for the day must still be able to book a room for an hour of it.
An exclusion constraint's predicate cannot look at another table, so the
resource's kind is denormalized onto booking as `resource_kind`, and a trigger
-- not the application -- fills it from `resource`. Every writer of booking
rows (the service, the seed, test fixtures) therefore gets it right without
knowing it exists.

If live overlapping desk bookings already exist, this revision refuses to run
rather than choosing which of someone's bookings to cancel. That is a decision
for a person, with the list in front of them.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

LIVE = "status NOT IN ('cancelled','released_no_show')"


def upgrade() -> None:
    op.add_column("booking", sa.Column("resource_kind", sa.Text(), nullable=True))
    op.execute(
        "UPDATE booking b SET resource_kind = r.kind FROM resource r WHERE r.id = b.resource_id"
    )
    op.alter_column("booking", "resource_kind", nullable=False)

    op.execute(
        """
        CREATE FUNCTION booking_set_resource_kind() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            SELECT kind INTO NEW.resource_kind FROM resource WHERE id = NEW.resource_id;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER booking_set_resource_kind
            BEFORE INSERT OR UPDATE OF resource_id ON booking
            FOR EACH ROW EXECUTE FUNCTION booking_set_resource_kind()
        """
    )

    clashes = op.get_bind().execute(sa.text(
        f"""
        SELECT a.id, b.id FROM booking a
        JOIN booking b ON a.user_id = b.user_id AND a.id < b.id AND a.during && b.during
        WHERE a.resource_kind = 'desk' AND b.resource_kind = 'desk'
          AND a.{LIVE} AND b.{LIVE}
        """
    )).fetchall()
    if clashes:
        pairs = ", ".join(f"{a}/{b}" for a, b in clashes[:20])
        raise RuntimeError(
            f"{len(clashes)} pair(s) of live desk bookings overlap for the same user "
            f"(booking ids: {pairs}). Cancel one of each pair, then re-run this migration."
        )

    # 'completed' stays in, for the same reason as booking_no_double_allocation:
    # a booking overlapping history would corrupt utilization retroactively.
    op.execute(
        f"""
        ALTER TABLE booking ADD CONSTRAINT booking_one_desk_per_user
            EXCLUDE USING gist (
                user_id WITH =,
                during  WITH &&
            ) WHERE ({LIVE} AND resource_kind = 'desk')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE booking DROP CONSTRAINT IF EXISTS booking_one_desk_per_user")
    op.execute("DROP TRIGGER IF EXISTS booking_set_resource_kind ON booking")
    op.execute("DROP FUNCTION IF EXISTS booking_set_resource_kind()")
    op.drop_column("booking", "resource_kind")
