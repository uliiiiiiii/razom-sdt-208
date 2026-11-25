"""Identity verification, user side: challenge word, submission, status."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from .claims import release_verified_only_claims_of
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
    # Lock order matches revoke/on_moderator_block: user row first, then the verification row.
    db.execute(select(User.id).where(User.id == v.user_id).with_for_update())
    db.execute(select(IdentityVerification.id).where(IdentityVerification.id == v.id).with_for_update())
    db.refresh(v)
    user = db.get(User, v.user_id)
    db.refresh(user)  # re-read under the lock: a block may have committed since the caller loaded it
    if v.status != "pending":
        raise HTTPException(409, "This submission has already been decided")
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


def revoke(db: Session, user: User, comment: str | None = None) -> None:
    """Take the badge away (caller commits): the approved row becomes `revoked`,
    the photo is deleted, and claims on verified-only requests go back to the map.
    Locks the user row first, so a concurrent claim either sees the revoke or is released by it."""
    db.flush()  # _lock refreshes the user; keep the caller's pending changes
    _lock(db, user)
    if not user.is_verified:
        return
    row = db.scalar(
        select(IdentityVerification)
        .where(IdentityVerification.user_id == user.id, IdentityVerification.status == "approved")
        .order_by(IdentityVerification.id.desc())
        .limit(1)
    )
    if row is not None:
        row.status, row.comment = "revoked", comment
    photo, user.photo_image_id = user.photo_image_id, None
    user.is_verified, user.verified_at = False, None
    db.flush()
    if photo is not None:
        db.execute(delete(VerificationImage).where(VerificationImage.id == photo))
    release_verified_only_claims_of(db, user.id)


def _expire(db: Session, where) -> int:
    """Set matching started/pending rows to `expired` and delete their images."""
    ids = db.scalars(
        update(IdentityVerification)
        .where(IdentityVerification.status.in_(("started", "pending")), where)
        .values(status="expired")
        .returning(IdentityVerification.id)
    ).all()
    if ids:
        db.execute(delete(VerificationImage).where(VerificationImage.verification_id.in_(ids)))
    return len(ids)


def on_moderator_block(db: Session, user: User) -> None:
    """A moderator's block (never the 3-report auto-block): revoke, and expire any
    submission in progress. Caller commits."""
    revoke(db, user)
    _expire(db, IdentityVerification.user_id == user.id)


def expire_stale(db: Session) -> int:
    """Daily purge: unreviewed submissions after PENDING_TTL, lapsed challenges."""
    now = _now()
    n = _expire(
        db,
        or_(
            and_(
                IdentityVerification.status == "pending",
                IdentityVerification.submitted_at < now - PENDING_TTL,
            ),
            and_(
                IdentityVerification.status == "started",
                IdentityVerification.challenge_expires_at < now,
            ),
        ),
    )
    db.commit()
    return n
