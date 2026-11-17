"""Privacy-by-role rules for help requests.

Who may see what:
- the author sees everything about their own request;
- the claiming volunteer sees the exact location and address only after the
  resident has accepted them, and only while the request is claimed/completed;
- a moderator sees them only through report review (caller passes
  via="report_review");
- everyone else sees the approximate location and no address.
Every reveal to someone other than the author is written to address_access_log.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .geo import lat_expr, lng_expr
from .models import AddressAccess, HelpRequest, User

ACTIVE_CLAIM_STATUSES = ("claimed", "completed")


def can_see_exact(req: HelpRequest, viewer: User) -> bool:
    if req.author_id == viewer.id:
        return True
    return (
        req.claimed_by == viewer.id
        and req.accepted_at is not None
        and req.status in ACTIVE_CLAIM_STATUSES
    )


def visible_to(req: HelpRequest, viewer: User) -> bool:
    """Open, unhidden requests of non-blocked authors are visible to any user;
    anything else only to its author and current claimer (others get 404)."""
    if viewer.id in (req.author_id, req.claimed_by):
        return True
    return req.status == "open" and not req.is_hidden and not req.author.is_blocked


def _confirmed_count(db: Session, volunteer_id: int) -> int:
    return db.scalar(
        select(func.count(HelpRequest.id)).where(
            HelpRequest.claimed_by == volunteer_id, HelpRequest.status == "confirmed"
        )
    ) or 0


def serialize_request(
    db: Session, req: HelpRequest, viewer: User, *, via: str | None = None
) -> dict:
    is_mine = req.author_id == viewer.id
    exact = via == "report_review" or can_see_exact(req, viewer)

    col = HelpRequest.location if exact else HelpRequest.approx_location
    coords = db.execute(
        select(lat_expr(col).label("lat"), lng_expr(col).label("lng")).where(
            HelpRequest.id == req.id
        )
    ).first()

    if exact and not is_mine:
        db.add(AddressAccess(request_id=req.id, user_id=viewer.id, via=via or "claim"))
        db.commit()

    claimer = None
    if is_mine and req.claimed_by is not None and req.status in ACTIVE_CLAIM_STATUSES:
        claimer = {
            "display_name": req.claimer.display_name,
            "confirmed_count": _confirmed_count(db, req.claimed_by),
        }

    return {
        "id": req.id,
        "category": req.category,
        "title": req.title,
        "description": req.description,
        "status": req.status,
        "latitude": coords.lat if coords else None,
        "longitude": coords.lng if coords else None,
        "address": req.address if exact else None,
        "exact_location": exact,
        "is_mine": is_mine,
        "is_claimer": req.claimed_by == viewer.id,
        "accepted": req.accepted_at is not None,
        "claimer": claimer,
        "created_at": req.created_at,
        "closed_at": req.closed_at,
    }
