"""SQLAlchemy models. TDD §3.

Conventions (TDD §3.1):
  - every table carries organization_id, including join tables
  - uuid primary keys via gen_random_uuid()
  - enumerations are text + CHECK, never native Postgres enums
  - all timestamps are timestamptz, stored UTC
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _org() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), nullable=False, index=True)


BOOKING_STATUSES = (
    "pending",
    "confirmed",
    "checked_in",
    "completed",
    "cancelled",
    "released_no_show",
)

#: Statuses that free the resource. The exclusion constraint ignores exactly these.
#: 'completed' is deliberately NOT here -- see TDD §4.1.
RELEASING_STATUSES = ("cancelled", "released_no_show")


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False, server_default="us")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (CheckConstraint("region IN ('us','eu')", name="organization_region_check"),)


class EmailDomain(Base):
    """FR-1.3 domain-based org discovery. Globally unique: one domain, one tenant."""

    __tablename__ = "email_domain"
    domain: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    idp_kind: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "idp_kind IN ('google','entra','magic_link')", name="email_domain_idp_check"
        ),
    )


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    home_site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    presence_visibility: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="everyone"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="app_user_org_email_key"),
        CheckConstraint(
            "presence_visibility IN ('everyone','team','nobody')", name="app_user_visibility_check"
        ),
        CheckConstraint("status IN ('active','deactivated')", name="app_user_status_check"),
    )


class Site(Base):
    __tablename__ = "site"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    opening_hours: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    capacity_cap: Mapped[int | None] = mapped_column(Integer)  # FR-6.3; NULL = no cap
    check_in_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )  # FR-4.7
    geofence_lat: Mapped[float | None] = mapped_column(Float)
    geofence_lng: Mapped[float | None] = mapped_column(Float)
    geofence_radius_m: Mapped[int] = mapped_column(Integer, nullable=False, server_default="150")


class Floor(Base):
    __tablename__ = "floor"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    plan_asset_key: Mapped[str | None] = mapped_column(Text)
    # Plan space (TDD §9.1) -- frozen on first upload so desks never move.
    plan_width: Mapped[int | None] = mapped_column(Integer)
    plan_height: Mapped[int | None] = mapped_column(Integer)


class Zone(Base):
    __tablename__ = "zone"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    floor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("floor.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    polygon: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    restricted_to_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Resource(Base):
    """Desks and rooms. The generalization PRD §6 asks for -- parking and lockers
    are a new `kind`, not a migration of the booking model."""

    __tablename__ = "resource"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id"), nullable=False
    )
    floor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("floor.id"))
    zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("zone.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    out_of_service_reason: Mapped[str | None] = mapped_column(Text)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FR-6.7
    plan_x: Mapped[float | None] = mapped_column(Float)
    plan_y: Mapped[float | None] = mapped_column(Float)
    plan_rotation: Mapped[float | None] = mapped_column(Float)
    qr_key_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __table_args__ = (
        UniqueConstraint("organization_id", "site_id", "name", name="resource_org_site_name_key"),
        CheckConstraint("kind IN ('desk','room')", name="resource_kind_check"),
        CheckConstraint(
            "status IN ('active','out_of_service','retired')", name="resource_status_check"
        ),
        Index("resource_attrs_gin", "attributes", postgresql_using="gin"),
    )


class Booking(Base):
    __tablename__ = "booking"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    # site_id and local_date are denormalized to serve the single timezone rule (TDD §3.4).
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resource.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )
    during: Mapped[object] = mapped_column(TSTZRANGE, nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )  # FR-2.10: the delegate, when booking on behalf
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    series_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    __table_args__ = (
        CheckConstraint(
            "status IN " + str(BOOKING_STATUSES).replace('"', "'"), name="booking_status_check"
        ),
    )


class SiteDayCapacity(Base):
    """FR-6.3 counter. The one serialization point in the booking path (TDD §4.2)."""

    __tablename__ = "site_day_capacity"
    organization_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site.id"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    booked_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cap: Mapped[int | None] = mapped_column(Integer)


class Policy(Base):
    """FR-6.x. Resolved by precedence group > site > org (TDD §4.3)."""

    __tablename__ = "policy"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rule_key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        CheckConstraint("scope_type IN ('org','site','group')", name="policy_scope_check"),
        UniqueConstraint(
            "organization_id", "scope_type", "scope_id", "rule_key", name="policy_scope_key"
        ),
    )


class IdempotencyKey(Base):
    """TDD §5.3. What makes the offline outbox safe to drain blindly."""

    __tablename__ = "idempotency_key"
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Job(Base):
    """TDD §12.1. Postgres-backed queue; no broker until the stated tripwire."""

    __tablename__ = "job"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','done','failed')", name="job_status_check"
        ),
        Index("job_claimable", "run_after", postgresql_where=text("status = 'pending'")),
    )


class UserGroup(Base):
    """Teams, departments, or arbitrary sets. Policies, zone permissions and the
    "who's in" views all hang off these (PRD §6)."""

    __tablename__ = "user_group"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="team")
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="user_group_org_name_key"),
        CheckConstraint("kind IN ('team','department','custom')", name="user_group_kind_check"),
    )


class GroupMember(Base):
    __tablename__ = "group_member"
    organization_id: Mapped[uuid.UUID] = _org()
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_group.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), primary_key=True
    )


class DayDeclaration(Base):
    """FR-5.5. One table serving three requirements: the team grid (FR-5.4),
    non-attendance (FR-5.5), and assigned-desk release (FR-6.7)."""

    __tablename__ = "day_declaration"
    organization_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('office','remote','leave')", name="day_declaration_kind_check"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = _pk()
    organization_id: Mapped[uuid.UUID] = _org()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
