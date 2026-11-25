"""Identity verification, user side: challenge word, submission, status."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .images import ImageRejected, encrypt, fingerprint, normalize_document_number, prepare_image
from .models import IdentityVerification, User, VerificationImage

CHALLENGE_TTL = timedelta(hours=24)
PENDING_TTL = timedelta(days=30)
KINDS = ("id_document", "selfie", "profile")

WORDS = tuple(
    """acorn amber anchor apple arrow aspen autumn badge baker banner barn basil beach bell berry
    birch blanket bloom boat bridge brook bucket butter cabin candle canoe canyon carpet castle
    cedar cherry circle clover cloud coast cocoa copper coral cotton creek crown daisy delta desert
    dove dragon drum eagle ember engine fabric falcon feather fern ferry field finch flame flint
    forest fox garden ginger glacier glove grain granite grove harbor hazel heron hill honey horizon
    island ivory jacket jungle kettle kite ladder lake lamp lantern leaf lemon lilac linen maple
    marble meadow melon mirror moon moss mountain needle nest oak ocean olive orchard otter paddle
    pearl pebble pepper pine planet plum pond poppy puddle quartz quilt rabbit rain raven reed ribbon
    ridge river robin rocket rose saddle sage sailor sand shadow shell silver sketch slate snow
    spark spoon spring squirrel star stone storm stream sugar summer sun swan table thistle thunder
    tiger timber tower trail tulip valley velvet violet walnut wave willow window winter wolf wool
    yarn zephyr""".split()
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def latest(db: Session, user: User) -> IdentityVerification | None:
    return db.scalar(
        select(IdentityVerification)
        .where(IdentityVerification.user_id == user.id)
        .order_by(IdentityVerification.id.desc())
        .limit(1)
    )


def _lock(db: Session, user: User) -> IdentityVerification | None:
    """Serialize this user's start/submit calls; returns their open row, if any."""
    db.execute(
        select(User.id).where(User.id == user.id).with_for_update()
    )
    db.refresh(user)
    return db.scalar(
        select(IdentityVerification).where(
            IdentityVerification.user_id == user.id,
            IdentityVerification.status.in_(("started", "pending")),
        )
    )


def start(db: Session, user: User) -> IdentityVerification:
    row = _lock(db, user)
    if user.is_verified or (row and row.status == "pending"):
        raise HTTPException(409, "Verification is already pending or complete")
    if row is None:
        row = IdentityVerification(user_id=user.id, status="started")
        db.add(row)
    row.challenge_word = "-".join(secrets.choice(WORDS) for _ in range(2))
    row.challenge_expires_at = _now() + CHALLENGE_TTL
    db.commit()
    return row


def submit(
    db: Session, user: User, files: dict[str, bytes], document_number: str
) -> IdentityVerification:
    row = _lock(db, user)
    if row is None or row.status != "started" or row.challenge_expires_at <= _now():
        raise HTTPException(409, "Start a new verification first")
    if not 4 <= len(normalize_document_number(document_number)) <= 32:
        raise HTTPException(422, "Document number must be 4 to 32 characters")
    try:
        images = [
            VerificationImage(verification_id=row.id, kind=k, data=encrypt(prepare_image(files[k])))
            for k in KINDS
        ]
    except ImageRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    db.add_all(images)
    row.document_fingerprint = fingerprint(document_number)
    row.status = "pending"
    row.submitted_at = _now()
    db.commit()
    return row


def duplicates_of(db: Session, v: IdentityVerification) -> list[User]:
    """Other users already approved with the same document fingerprint."""
    if v.document_fingerprint is None:
        return []
    return list(
        db.scalars(
            select(User)
            .join(IdentityVerification, IdentityVerification.user_id == User.id)
            .where(
                IdentityVerification.status == "approved",
                IdentityVerification.document_fingerprint == v.document_fingerprint,
                User.id != v.user_id,
            )
            .distinct()
        )
    )


def decide(
    db: Session,
    v: IdentityVerification,
    moderator: User,
    decision: Literal["approved", "rejected"],
    comment: str | None,
) -> IdentityVerification:
    if v.user_id == moderator.id:
        raise HTTPException(403, "You can't review your own verification")
    db.execute(select(IdentityVerification.id).where(IdentityVerification.id == v.id).with_for_update())
    db.refresh(v)
    if v.status != "pending":
        raise HTTPException(409, "This submission has already been decided")
    user = db.get(User, v.user_id)
    mine = VerificationImage.verification_id == v.id
    if decision == "approved":
        if user.is_blocked:
            raise HTTPException(409, "This user is blocked")
        if user.photo_image_id is not None:  # replace the previous profile photo
            db.execute(delete(VerificationImage).where(VerificationImage.id == user.photo_image_id))
        db.execute(delete(VerificationImage).where(mine, VerificationImage.kind != "profile"))
        db.flush()
        user.photo_image_id = db.scalar(
            select(VerificationImage.id).where(mine, VerificationImage.kind == "profile")
        )
        user.is_verified = True
        user.verified_at = _now()
    else:
        db.execute(delete(VerificationImage).where(mine))
    v.status, v.comment, v.decided_by, v.decided_at = decision, comment, moderator.id, _now()
    db.commit()
    return v
