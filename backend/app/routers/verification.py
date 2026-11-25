"""Identity verification, user side: /api/me/verification and /api/me/settings.

No `from __future__ import annotations`: the routes are rate limited (see ratelimit.py).
"""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from .. import verification as v
from ..database import get_db
from ..deps import get_current_user
from ..images import MAX_UPLOAD_BYTES
from ..models import User
from ..ratelimit import VERIFICATION_START_LIMIT, VERIFICATION_SUBMIT_LIMIT, limiter
from ..schemas import ChallengeOut, MyVerification, SettingsIn, SettingsOut

router = APIRouter(prefix="/me", tags=["verification"])


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
