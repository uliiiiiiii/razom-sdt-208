"""Identity verification: /api/me/verification and /api/me/settings, the moderator
review, and profile photos (/api/users/{id}/photo).

No `from __future__ import annotations`: the routes are rate limited (see ratelimit.py).
"""
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import verification as v
from ..claims import expire_unaccepted_claims
from ..database import get_db
from ..deps import Page, get_current_user, page_params, paginate, require_roles
from ..images import MAX_UPLOAD_BYTES, decrypt
from ..models import IdentityVerification, User, VerificationAccess, VerificationImage
from ..privacy import photo_visible_to
from ..ratelimit import VERIFICATION_START_LIMIT, VERIFICATION_SUBMIT_LIMIT, limiter
from ..schemas import (
    ChallengeOut,
    MyVerification,
    SettingsIn,
    SettingsOut,
    VerificationAccessEntry,
    VerificationDecision,
    VerificationReview,
)

router = APIRouter(prefix="/me", tags=["verification"])

# decrypted images must not sit in any cache
NO_STORE = {"Cache-Control": "private, no-store"}


def _mine(row) -> dict:
    if row is None:
        return {"status": "none"}
    started = row.status == "started"
    return {
        "status": row.status,
        "word": row.challenge_word if started else None,
        "expires_at": row.challenge_expires_at if started else None,
        "submitted_at": row.submitted_at,
        "decided_at": row.decided_at,
        "comment": row.comment,
    }


@router.post("/verification/start", response_model=ChallengeOut)
@limiter.limit(VERIFICATION_START_LIMIT)
def start(
    request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    row = v.start(db, user)
    return {"word": row.challenge_word, "expires_at": row.challenge_expires_at}


@router.post("/verification", response_model=MyVerification)
@limiter.limit(VERIFICATION_SUBMIT_LIMIT)
def submit(
    request: Request,
    id_document: UploadFile = File(...),
    selfie: UploadFile = File(...),
    profile: UploadFile = File(...),
    document_number: str = Form(..., max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # one byte over the cap is enough for prepare_image to reject it
    files = {
        k: f.file.read(MAX_UPLOAD_BYTES + 1)
        for k, f in (("id_document", id_document), ("selfie", selfie), ("profile", profile))
    }
    return _mine(v.submit(db, user, files, document_number))


@router.get("/verification", response_model=MyVerification)
def my_verification(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _mine(v.latest(db, user))


@router.patch("/settings", response_model=SettingsOut)
def update_settings(
    payload: SettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    user.only_verified_residents = payload.only_verified_residents
    db.commit()
    return {"only_verified_residents": user.only_verified_residents}


# ---------------------------------------------------------------------------
# moderator review
# ---------------------------------------------------------------------------
moderation_router = APIRouter(prefix="/moderation", tags=["moderation"])
moderator = require_roles("moderator")


def _review(db: Session, row: IdentityVerification, images: bool = False) -> dict:
    u = db.get(User, row.user_id)
    out = {
        "id": row.id,
        "user": {"id": u.id, "display_name": u.display_name, "roles": u.roles},
        "submitted_at": row.submitted_at,
        "duplicates": v.duplicates_of(db, row),
    }
    if images:
        out["images"] = list(
            db.scalars(
                select(VerificationImage.kind).where(VerificationImage.verification_id == row.id)
            )
        )
    return out


def _theirs(db: Session, vid: int, mod: User) -> IdentityVerification:
    row = db.get(IdentityVerification, vid)
    if row is None:
        raise HTTPException(404, "Verification not found")
    if row.user_id == mod.id:
        raise HTTPException(403, "You can't review your own verification")
    return row


@moderation_router.get("/verifications", response_model=list[VerificationReview])
def review_queue(db: Session = Depends(get_db), mod: User = Depends(moderator)):
    rows = db.scalars(
        select(IdentityVerification)
        .join(User, User.id == IdentityVerification.user_id)
        .where(
            IdentityVerification.status == "pending",
            IdentityVerification.user_id != mod.id,
            User.is_blocked.is_(False),
        )
        .order_by(IdentityVerification.submitted_at, IdentityVerification.id)
    )
    return [_review(db, r) for r in rows]


@moderation_router.get("/verifications/{vid}", response_model=VerificationReview)
def review_detail(vid: int, db: Session = Depends(get_db), mod: User = Depends(moderator)):
    return _review(db, _theirs(db, vid, mod), images=True)


@moderation_router.get("/verifications/{vid}/images/{kind}", response_class=Response)
def review_image(
    vid: int,
    kind: Literal["id_document", "selfie", "profile"],
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
):
    row = _theirs(db, vid, mod)
    image = db.scalar(
        select(VerificationImage).where(
            VerificationImage.verification_id == vid, VerificationImage.kind == kind
        )
    )
    if row.status != "pending" or image is None:
        raise HTTPException(404, "Image not found")
    db.add(VerificationAccess(verification_id=vid, moderator_id=mod.id, kind=kind))
    db.commit()
    return Response(decrypt(image.data), media_type="image/jpeg", headers=NO_STORE)


@moderation_router.patch("/verifications/{vid}", response_model=VerificationReview)
def review_decide(
    vid: int,
    payload: VerificationDecision,
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
):
    row = _theirs(db, vid, mod)
    return _review(db, v.decide(db, row, mod, payload.decision, payload.comment))


@moderation_router.get("/verification-access-log", response_model=list[VerificationAccessEntry])
def verification_access_log(
    verification_id: int | None = None,
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
):
    stmt = select(VerificationAccess, User).join(User, User.id == VerificationAccess.moderator_id)
    if verification_id is not None:
        stmt = stmt.where(VerificationAccess.verification_id == verification_id)
    return [
        {
            "id": a.id,
            "verification_id": a.verification_id,
            "moderator": {"id": u.id, "display_name": u.display_name},
            "kind": a.kind,
            "accessed_at": a.accessed_at,
        }
        for a, u in db.execute(paginate(stmt, VerificationAccess.id, page)).all()
    ]


# ---------------------------------------------------------------------------
# profile photos
# ---------------------------------------------------------------------------
users_router = APIRouter(prefix="/users", tags=["verification"])


@users_router.get("/{user_id}/photo", response_class=Response)
def user_photo(user_id: int, db: Session = Depends(get_db), viewer: User = Depends(get_current_user)):
    """Unknown user, no photo and not allowed are the same 404, so the answer
    never tells whether someone has a photo. Views aren't logged: the photo is
    meant for the other party."""
    expire_unaccepted_claims(db)  # a lapsed claim no longer shows the volunteer's photo
    owner = db.get(User, user_id)
    image = (
        db.get(VerificationImage, owner.photo_image_id)
        if owner is not None and owner.is_verified and owner.photo_image_id is not None
        else None
    )
    if image is None or not photo_visible_to(db, owner, viewer):
        raise HTTPException(404, "Photo not found")
    return Response(decrypt(image.data), media_type="image/jpeg", headers=NO_STORE)
