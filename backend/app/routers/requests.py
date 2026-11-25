"""Help-requests router: the request lifecycle state machine.

open --claim--> claimed --accept (resident)--> claimed+accepted --complete--> completed
completed --confirm--> confirmed | completed --reopen--> open
claimed --release (volunteer) / decline (resident, before accept)--> open
open|claimed --cancel--> cancelled

Who sees the exact address is decided in app/privacy.py.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from ..claims import active_claim_id, expire_unaccepted_claims
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..geo import point_wkt, round_location
from ..models import ClaimHistory, HelpRequest, User
from ..privacy import serialize_request, visible_to
from ..ratelimit import CREATE_REQUEST_LIMIT, limiter
from ..schemas import ClaimRef, RequestCreate, RequestOut

router = APIRouter(prefix="/requests", tags=["help-requests"])

MAX_ACTIVE_PER_RESIDENT = 3
MAX_CLAIMS_PER_VOLUNTEER = 2
MAX_CLAIMS_PER_DAY = 5  # claim -> release loops would otherwise harvest addresses

NOT_FOUND = "Request not found"
VERIFIED_ONLY = "This request is for verified volunteers only"

# Allowed transitions per action: action -> (allowed from-states, to-state).
# Keyed by action, not just by state, so e.g. 'reopen' can't be used to
# kick a volunteer off a claimed request. 'claim' (open -> claimed) is an
# atomic UPDATE in claim_request.
TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "accept": ({"claimed"}, "claimed"),
    "decline": ({"claimed"}, "open"),
    "release": ({"claimed"}, "open"),
    "complete": ({"claimed"}, "completed"),
    "confirm": ({"completed"}, "confirmed"),
    "reopen": ({"completed"}, "open"),
    "cancel": ({"open", "claimed"}, "cancelled"),
}


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(CREATE_REQUEST_LIMIT)
def create_request(
    request: Request,
    payload: RequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("resident")),
) -> dict:
    _lock_user(db, user)
    active = db.scalar(
        select(func.count(HelpRequest.id)).where(
            HelpRequest.author_id == user.id,
            HelpRequest.status.in_(("open", "claimed", "completed")),
        )
    ) or 0
    if active >= MAX_ACTIVE_PER_RESIDENT:
        raise HTTPException(
            409, detail=f"A resident cannot have more than {MAX_ACTIVE_PER_RESIDENT} active requests"
        )

    approx_lat, approx_lng = round_location(payload.latitude, payload.longitude)
    help_request = HelpRequest(
        author_id=user.id,
        category=payload.category,
        title=payload.title,
        description=payload.description,
        status="open",
        location=point_wkt(payload.latitude, payload.longitude),
        approx_location=point_wkt(approx_lat, approx_lng),
        address=payload.address,
        verified_only=payload.verified_only,
    )
    db.add(help_request)
    db.commit()
    db.refresh(help_request)
    return serialize_request(db, help_request, user)


@router.get("/{request_id}", response_model=RequestOut)
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return serialize_request(db, _get_visible(db, request_id, user), user)


@router.patch("/{request_id}/claim", response_model=RequestOut)
def claim_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("volunteer")),
) -> dict:
    expire_unaccepted_claims(db)
    _lock_user(db, user)
    active_claims = db.scalar(
        select(func.count(HelpRequest.id)).where(
            HelpRequest.claimed_by == user.id,
            HelpRequest.status == "claimed",
        )
    ) or 0
    if active_claims >= MAX_CLAIMS_PER_VOLUNTEER:
        raise HTTPException(
            409,
            detail=f"A volunteer cannot hold more than {MAX_CLAIMS_PER_VOLUNTEER} claimed requests",
        )
    claims_today = db.scalar(
        select(func.count(ClaimHistory.id)).where(
            ClaimHistory.volunteer_id == user.id,
            ClaimHistory.claimed_at > func.now() - text("interval '24 hours'"),
        )
    ) or 0
    if claims_today >= MAX_CLAIMS_PER_DAY:
        raise HTTPException(
            409, detail=f"A volunteer cannot claim more than {MAX_CLAIMS_PER_DAY} requests in 24 hours"
        )
    declined = db.scalar(
        select(ClaimHistory.id).where(
            ClaimHistory.request_id == request_id,
            ClaimHistory.volunteer_id == user.id,
            ClaimHistory.outcome == "declined",
        )
    )
    if declined:
        raise HTTPException(409, detail="The resident declined your help with this request")

    # Atomic, concurrency-safe claim: only succeeds if the row is still 'open'
    # (and, for a verified-only request, the volunteer is verified).
    result = db.execute(
        text(
            "UPDATE help_requests "
            "SET status = 'claimed', claimed_by = :uid, claimed_at = now(), updated_at = now() "
            "WHERE id = :rid AND status = 'open' AND NOT is_hidden AND author_id <> :uid "
            "AND author_id NOT IN (SELECT id FROM users WHERE is_blocked) "
            # read at UPDATE time, not from the user loaded earlier: a revoke may commit in between
            "AND (NOT verified_only OR (SELECT is_verified FROM users WHERE id = :uid)) "
            "RETURNING id"
        ),
        {"uid": user.id, "rid": request_id},
    )
    if result.first() is None:
        db.rollback()
        request = db.get(HelpRequest, request_id)
        if not request or request.is_hidden or request.author.is_blocked:
            raise HTTPException(404, detail=NOT_FOUND)
        if request.author_id == user.id:
            raise HTTPException(409, detail="You cannot claim your own request")
        if request.verified_only and not user.is_verified:
            raise HTTPException(403, detail=VERIFIED_ONLY)
        # e.g. lost a race with another volunteer; the status isn't disclosed
        raise HTTPException(409, detail="Request is no longer open")
    db.add(ClaimHistory(request_id=request_id, volunteer_id=user.id))
    db.commit()
    return serialize_request(db, db.get(HelpRequest, request_id), user)


@router.patch("/{request_id}/accept", response_model=RequestOut)
def accept_volunteer(
    request_id: int,
    payload: ClaimRef,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Resident accepts the claiming volunteer; only now is the address revealed to them."""
    request = _get_own(db, request_id, user, "accept the volunteer for")
    _check_same_claim(db, request, payload.claim_id)
    if request.accepted_at is not None:
        raise HTTPException(409, detail="The volunteer is already accepted")
    _transition(request, "accept")
    request.accepted_at = _now()
    return _save(db, request, user)


@router.patch("/{request_id}/decline", response_model=RequestOut)
def decline_volunteer(
    request_id: int,
    payload: ClaimRef,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Resident declines the claiming volunteer; they can't claim this request again."""
    request = _get_own(db, request_id, user, "decline the volunteer for")
    _check_same_claim(db, request, payload.claim_id)
    if request.accepted_at is not None:
        raise HTTPException(409, detail="The volunteer is already accepted; cancel the request instead")
    _transition(request, "decline")
    _end_claim(db, request, "declined")
    return _save(db, request, user)


@router.patch("/{request_id}/release", response_model=RequestOut)
def release_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    request = _get_claimed_by_me(db, request_id, user, "release")
    _transition(request, "release")
    _end_claim(db, request, "released")
    return _save(db, request, user)


@router.patch("/{request_id}/complete", response_model=RequestOut)
def complete_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    request = _get_claimed_by_me(db, request_id, user, "complete")
    if request.status == "claimed" and request.accepted_at is None:
        raise HTTPException(409, detail="The resident has not accepted your help yet")
    _transition(request, "complete")
    _mark_claim(db, request, "active", "completed")
    return _save(db, request, user)


@router.patch("/{request_id}/confirm", response_model=RequestOut)
def confirm_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    request = _get_own(db, request_id, user, "confirm")
    _transition(request, "confirm")
    request.closed_at = _now()
    return _save(db, request, user)


@router.patch("/{request_id}/reopen", response_model=RequestOut)
def reopen_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Resident marks a 'completed' request as not resolved -> back to 'open'."""
    request = _get_own(db, request_id, user, "reopen")
    _transition(request, "reopen")
    _mark_claim(db, request, "completed", "reopened")
    _clear_claim(request)
    return _save(db, request, user)


@router.patch("/{request_id}/cancel", response_model=RequestOut)
def cancel_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    request = _get_own(db, request_id, user, "cancel")
    _transition(request, "cancel")
    if request.claimed_by is not None:
        _end_claim(db, request, "cancelled")
    request.closed_at = _now()
    return _save(db, request, user)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lock_user(db: Session, user: User) -> None:
    """Lock the user's row until commit so concurrent requests from the same
    user can't all pass a count-based limit check at once."""
    db.execute(select(User.id).where(User.id == user.id).with_for_update())


def _get_visible(db: Session, request_id: int, user: User, *, lock: bool = False) -> HelpRequest:
    # lock=True for state changes: concurrent claim/release/accept/cancel on the
    # same request then run one after another instead of interleaving
    request = db.get(HelpRequest, request_id, with_for_update=lock)
    if not request or not visible_to(request, user):
        raise HTTPException(404, detail=NOT_FOUND)
    return request


def _get_own(db: Session, request_id: int, user: User, verb: str) -> HelpRequest:
    request = _get_visible(db, request_id, user, lock=True)
    if request.author_id != user.id:
        raise HTTPException(403, detail=f"Only the resident who created this request can {verb} it")
    return request


def _get_claimed_by_me(db: Session, request_id: int, user: User, verb: str) -> HelpRequest:
    request = _get_visible(db, request_id, user, lock=True)
    if request.claimed_by != user.id:
        raise HTTPException(403, detail=f"Only the volunteer who claimed this request can {verb} it")
    return request


def _check_same_claim(db: Session, request: HelpRequest, claim_id: int) -> None:
    if request.status != "claimed" or active_claim_id(db, request) != claim_id:
        raise HTTPException(
            409, detail="The volunteer for this request has changed; review them again"
        )


def _transition(request: HelpRequest, action: str) -> None:
    from_states, target = TRANSITIONS[action]
    if request.status not in from_states:
        raise HTTPException(
            409,
            detail=f"Cannot {action} a request in status '{request.status}'",
        )
    request.status = target


def _mark_claim(db: Session, request: HelpRequest, from_outcome: str, to_outcome: str) -> None:
    db.execute(
        update(ClaimHistory)
        .where(
            ClaimHistory.request_id == request.id,
            ClaimHistory.volunteer_id == request.claimed_by,
            ClaimHistory.outcome == from_outcome,
        )
        .values(outcome=to_outcome)
    )


def _clear_claim(request: HelpRequest) -> None:
    request.claimed_by = None
    request.claimed_at = None
    request.accepted_at = None


def _end_claim(db: Session, request: HelpRequest, outcome: str) -> None:
    _mark_claim(db, request, "active", outcome)
    _clear_claim(request)


def _save(db: Session, request: HelpRequest, user: User) -> dict:
    request.updated_at = _now()
    db.commit()
    db.refresh(request)
    return serialize_request(db, request, user)
