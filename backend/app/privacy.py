"""Privacy-by-role rules for help requests.

Who may see what:
- the author sees everything about their own request;
- the claiming volunteer sees the exact location and address only after the
  resident has accepted them, and only while the request is 'claimed' (once
  they mark it completed they no longer need it);
- a moderator sees them only through report review (caller passes
  via="report_review");
- everyone else sees the approximate location and no address.
Every reveal to someone other than the author is written to address_access_log.

Profile photos (verified users only) follow the same moments: the volunteer's
photo once they claim, the resident's once they accept (photo_visible_to).
"""
from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .claims import active_claim_id
from .models import HelpRequest, User

ACTIVE_CLAIM_STATUSES = ("claimed", "completed")


def can_see_exact(req: HelpRequest, viewer: User) -> bool:
    if req.author_id == viewer.id:
        return True
    return (
        req.claimed_by == viewer.id
        and req.accepted_at is not None
        and req.status == "claimed"
    )


def visible_to(req: HelpRequest, viewer: User) -> bool:
    """Open, unhidden requests of non-blocked authors are visible to any user;
    anything else only to its author and current claimer (others get 404)."""
    if viewer.id in (req.author_id, req.claimed_by):
        return True
    return req.status == "open" and not req.is_hidden and not req.author.is_blocked


def photo_url(user: User) -> str | None:
    return f"/api/users/{user.id}/photo" if user.is_verified else None


def photo_visible_to(db: Session, owner: User, viewer: User) -> bool:
    """May `viewer` see `owner`'s profile photo? (The caller 404s otherwise.)"""
    if viewer.is_moderator:
        return True
    if owner.is_blocked:  # a blocked account is invisible, whoever it dealt with
        return False
    if owner.id == viewer.id:
        return True
    # the volunteer's photo: to the author of a request they currently hold
    holds = db.scalar(
        select(HelpRequest.id)
        .where(
            HelpRequest.author_id == viewer.id,
            HelpRequest.claimed_by == owner.id,
            HelpRequest.status.in_(ACTIVE_CLAIM_STATUSES),
        )
        .limit(1)
    )
    if holds is not None:
        return True
    # the resident's photo: to the accepted claimer, exactly while the address is visible
    claimed = db.scalars(
        select(HelpRequest).where(
            HelpRequest.author_id == owner.id, HelpRequest.claimed_by == viewer.id
        )
    )
    return any(can_see_exact(r, viewer) for r in claimed)


# Repeat views by the same person within this window are one log entry, so
# reloading a list doesn't push older entries out of the moderators' view.
ACCESS_LOG_WINDOW = "1 hour"


def _log_access(db: Session, request_id: int, user_id: int, via: str) -> None:
    inserted = db.execute(
        text(
            """
            INSERT INTO address_access_log (request_id, user_id, via)
            SELECT :r, :u, :v
             WHERE NOT EXISTS (
                   SELECT 1 FROM address_access_log
                    WHERE request_id = :r AND user_id = :u AND via = :v
                      AND accessed_at > now() - CAST(:w AS interval))
            """
        ),
        {"r": request_id, "u": user_id, "v": via, "w": ACCESS_LOG_WINDOW},
    ).rowcount
    if inserted:
        db.commit()  # skipped otherwise: a commit expires every loaded row


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

    if exact and not is_mine:
        _log_access(db, req.id, viewer.id, via or "claim")

    claimer = None
    if is_mine and req.claimed_by is not None and req.status in ACTIVE_CLAIM_STATUSES:
        claimer = {
            "claim_id": active_claim_id(db, req),
            "display_name": req.claimer.display_name,
            "confirmed_count": _confirmed_count(db, req.claimed_by),
            "user_id": req.claimed_by,
            "is_verified": req.claimer.is_verified,
            "photo_url": photo_url(req.claimer),
        }

    return {
        "id": req.id,
        "category": req.category,
        "title": req.title,
        "description": req.description,
        "status": req.status,
        "latitude": req.exact_lat if exact else req.approx_lat,
        "longitude": req.exact_lng if exact else req.approx_lng,
        "address": req.address if exact else None,
        "exact_location": exact,
        "is_mine": is_mine,
        "is_claimer": req.claimed_by == viewer.id,
        "accepted": req.accepted_at is not None,
        "is_hidden": req.is_hidden,
        "claimer": claimer,
        "verified_only": req.verified_only,
        "author_verified": req.author.is_verified,
        # the author's photo goes only to the accepted claimer (can_see_exact, not report review)
        "author_photo_url": photo_url(req.author)
        if not is_mine and can_see_exact(req, viewer)
        else None,
        "created_at": req.created_at,
        "closed_at": req.closed_at,
    }
