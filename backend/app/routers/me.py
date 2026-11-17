"""The current user's own lists: /api/me/..."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import HelpRequest, User
from ..privacy import serialize_request
from ..schemas import RequestOut

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/requests", response_model=list[RequestOut])
def my_requests(
    db: Session = Depends(get_db), user: User = Depends(require_roles("resident"))
) -> list[dict]:
    rows = db.scalars(
        select(HelpRequest)
        .where(HelpRequest.author_id == user.id)
        .order_by(HelpRequest.created_at.desc())
    )
    return [serialize_request(db, r, user) for r in rows]


@router.get("/claims", response_model=list[RequestOut])
def my_claims(
    db: Session = Depends(get_db), user: User = Depends(require_roles("volunteer"))
) -> list[dict]:
    rows = db.scalars(
        select(HelpRequest)
        .where(HelpRequest.claimed_by == user.id)
        .order_by(HelpRequest.updated_at.desc())
    )
    return [serialize_request(db, r, user) for r in rows]
