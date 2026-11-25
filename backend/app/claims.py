"""Claim bookkeeping shared by requests, map, my-lists and moderation."""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import ClaimHistory, HelpRequest

# A claim the resident hasn't accepted within this time goes back to the map,
# so fake volunteers can't take requests off the map indefinitely.
ACCEPT_WINDOW_HOURS = 12


def active_claim_id(db: Session, req: HelpRequest) -> int | None:
    """claim_history id of the current claim; the resident must send it back on
    accept/decline so they approve the volunteer they actually saw."""
    if req.claimed_by is None:
        return None
    return db.scalar(
        select(ClaimHistory.id)
        .where(
            ClaimHistory.request_id == req.id,
            ClaimHistory.volunteer_id == req.claimed_by,
            ClaimHistory.outcome == "active",
        )
        .order_by(ClaimHistory.id.desc())
        .limit(1)
    )


def _reopen(db: Session, where: str, params: dict) -> int:
    """Return matching claimed requests to 'open' and mark their claims released."""
    rows = db.execute(
        text(
            f"""
            UPDATE help_requests
               SET status = 'open', claimed_by = NULL, claimed_at = NULL,
                   accepted_at = NULL, updated_at = now()
             WHERE status = 'claimed' AND {where}
            RETURNING id
            """
        ),
        params,
    ).all()
    if rows:
        db.execute(
            text(
                "UPDATE claim_history SET outcome = 'released' "
                "WHERE outcome = 'active' AND request_id = ANY(:ids)"
            ),
            {"ids": [r.id for r in rows]},
        )
    return len(rows)


def expire_unaccepted_claims(db: Session) -> int:
    n = _reopen(
        db,
        "accepted_at IS NULL AND claimed_at < now() - make_interval(hours => :h)",
        {"h": ACCEPT_WINDOW_HOURS},
    )
    db.commit()
    return n


def release_claims_of(db: Session, volunteer_id: int) -> int:
    """A blocked volunteer's claimed requests go back to the map (caller commits)."""
    return _reopen(db, "claimed_by = :v", {"v": volunteer_id})


def release_verified_only_claims_of(db: Session, volunteer_id: int) -> int:
    """A revoked volunteer's claims on verified-only requests go back to the map (caller commits)."""
    return _reopen(db, "claimed_by = :v AND verified_only", {"v": volunteer_id})
