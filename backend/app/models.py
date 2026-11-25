"""ORM models (SQLAlchemy + GeoAlchemy2).

The schema itself is owned by the Alembic migrations in app/migrations;
these models must be kept in step with them.
"""
from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Integer,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from .database import Base
from .geo import lat_expr, lng_expr


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_resident: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_volunteer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_organization: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_moderator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # blocked by the 3-reports rule (a dismissed report undoes only these)
    auto_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    photo_image_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "verification_images.id", ondelete="SET NULL", use_alter=True,
            name="fk_users_photo_image",
        ),
    )
    only_verified_residents: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def role_list(self) -> list[str]:
        roles = []
        if self.is_resident:
            roles.append("resident")
        if self.is_volunteer:
            roles.append("volunteer")
        if self.is_organization:
            roles.append("organization")
        if self.is_moderator:
            roles.append("moderator")
        return roles

    @property
    def roles(self) -> list[str]:
        return self.role_list()


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    org_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(
        Text, default="pending", nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )



class HelpRequest(Base):
    __tablename__ = "help_requests"
    __table_args__ = (
        CheckConstraint(
            "status NOT IN ('claimed','completed') OR claimed_by IS NOT NULL",
            name="chk_claim_consistency",
        ),
        CheckConstraint(
            "accepted_at IS NULL OR claimed_by IS NOT NULL",
            name="chk_accept_needs_claimer",
        ),
        CheckConstraint(
            "category IN ('charging','groceries','medicine','water',"
            "'transport','pets','other')",
            name="chk_requests_category_ck",
        ),
        CheckConstraint(
            "status IN ('open','claimed','completed','confirmed','cancelled')",
            name="chk_requests_status_ck",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    author_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="open", nullable=False)
    location: Mapped[object] = mapped_column(Geography("POINT", srid=4326), nullable=False)
    approx_location: Mapped[object | None] = mapped_column(Geography("POINT", srid=4326))
    address: Mapped[str | None] = mapped_column(Text)
    claimed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # set when the resident accepts the claiming volunteer; address revealed only after this
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # set on confirm/cancel; drives address retention
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    author: Mapped[User] = relationship("User", foreign_keys=[author_id])
    claimer: Mapped[User | None] = relationship("User", foreign_keys=[claimed_by])


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, default="other", nullable=False)
    location: Mapped[object] = mapped_column(Geography("POINT", srid=4326), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slots_total: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="open", nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OpportunitySignup(Base):
    __tablename__ = "opportunity_signups"
    __table_args__ = (UniqueConstraint("opportunity_id", "volunteer_id", name="uniq_signup"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
    )
    volunteer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    signed_up_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attended: Mapped[bool | None] = mapped_column(Boolean)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("reporter_id", "target_type", "target_id", name="uniq_report"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClaimHistory(Base):
    """Every claim of a request, including released/declined ones."""

    __tablename__ = "claim_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("help_requests.id", ondelete="CASCADE"), nullable=False
    )
    volunteer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    outcome: Mapped[str] = mapped_column(Text, default="active", nullable=False)


class AddressAccess(Base):
    """Audit trail: who was shown a request's exact address, and how."""

    __tablename__ = "address_access_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("help_requests.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    via: Mapped[str] = mapped_column(Text, nullable=False)


class VerificationLog(Base):
    __tablename__ = "verification_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    moderator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IdentityVerification(Base):
    __tablename__ = "identity_verifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started','pending','approved','rejected','expired','revoked')",
            name="chk_verification_status_ck",
        ),
        Index(
            "uniq_open_verification", "user_id", unique=True,
            postgresql_where=text("status IN ('started','pending')"),
        ),
        Index("ix_verification_fingerprint", "document_fingerprint"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    challenge_word: Mapped[str] = mapped_column(Text, nullable=False)
    challenge_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    document_fingerprint: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VerificationImage(Base):
    __tablename__ = "verification_images"
    __table_args__ = (
        UniqueConstraint("verification_id", "kind", name="uniq_verification_image"),
        CheckConstraint(
            "kind IN ('id_document','selfie','profile')",
            name="chk_verification_image_kind_ck",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    verification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("identity_verifications.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # Fernet token
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VerificationAccess(Base):
    """Audit trail: which moderator viewed which verification image."""

    __tablename__ = "verification_access_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    verification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("identity_verifications.id", ondelete="CASCADE"), nullable=False
    )
    moderator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Coordinates (and the sign-up count) load in the same SELECT as the row, so
# serializing a list doesn't cost one extra query per item. Like any loaded
# attribute they are stale until the next commit/refresh.
_req, _opp = HelpRequest.__table__.c, Opportunity.__table__.c
HelpRequest.exact_lat = column_property(lat_expr(_req.location))
HelpRequest.exact_lng = column_property(lng_expr(_req.location))
HelpRequest.approx_lat = column_property(lat_expr(_req.approx_location))
HelpRequest.approx_lng = column_property(lng_expr(_req.approx_location))
Opportunity.lat = column_property(lat_expr(_opp.location))
Opportunity.lng = column_property(lng_expr(_opp.location))
# display only: under concurrent sign-ups check the count with a fresh query
Opportunity.slots_taken = column_property(
    select(func.count(OpportunitySignup.id))
    .where(OpportunitySignup.opportunity_id == _opp.id)
    .correlate_except(OpportunitySignup)
    .scalar_subquery()
)
