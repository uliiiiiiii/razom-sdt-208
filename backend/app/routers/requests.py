"""Help-requests router — the core Alpha scenario.

Implements the request lifecycle state machine and privacy-by-role rules:
  register -> login -> create request -> claim on map -> complete -> confirm
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..geo import round_location
from ..models import HelpRequest, User
from ..schemas import RequestCreate, RequestMapItem, RequestOut

router = APIRouter(prefix="/requests", tags=["help-requests"])

MAX_ACTIVE_PER_RESIDENT = 3
MAX_CLAIMS_PER_VOLUNTEER = 2

# Allowed transitions per action: action -> (allowed from-states, to-state).
# Keyed by action, not just by state, so e.g. 'reopen' can't be used to
# kick a volunteer off a claimed request. 'claim' (open -> claimed) is an
# atomic UPDATE in claim_request.
TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "release": ({"claimed"}, "open"),
    "complete": ({"claimed"}, "completed"),
    "confirm": ({"completed"}, "confirmed"),
    "reopen": ({"completed"}, "open"),
    "cancel": ({"open", "claimed"}, "cancelled"),
}


def _point_wkt(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def _lat_expr(col) -> object:
    # ST_Y/ST_X require geometry, not geography -> cast.
    return func.ST_Y(cast(col, Geometry(srid=4326)))


def _lng_expr(col) -> object:
    return func.ST_X(cast(col, Geometry(srid=4326)))



@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: RequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    if not user.is_resident:
        raise HTTPException(403, detail="Only residents can create help requests")

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
    request = HelpRequest(
        author_id=user.id,
        category=payload.category,
        title=payload.title,
        description=payload.description,
        status="open",
        location=_point_wkt(payload.latitude, payload.longitude),
        approx_location=_point_wkt(approx_lat, approx_lng),
        address=payload.address,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return _serialize(request, user, db)


@router.get("/map", response_model=list[RequestMapItem])
def search_map(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(2000, gt=0, le=200000),
    category: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Radius search using PostGIS. Returns APPROXIMATE locations only."""
    point = _point_wkt(lat, lng)
    stmt = (
        select(
            HelpRequest.id,
            HelpRequest.category,
            HelpRequest.title,
            HelpRequest.status,
            _lat_expr(HelpRequest.approx_location).label("lat"),
            _lng_expr(HelpRequest.approx_location).label("lng"),
            func.ST_Distance(HelpRequest.approx_location, point).label("dist"),
        )
        .where(HelpRequest.status == "open")
        .where(func.ST_DWithin(HelpRequest.approx_location, point, radius))
    )
    if category:
        stmt = stmt.where(HelpRequest.category == category)
    stmt = stmt.order_by(text("dist"))
    rows = db.execute(stmt).all()
    return [
        {
            "id": r.id,
            "category": r.category,
            "title": r.title,
            "status": r.status,
            "latitude": r.lat,
            "longitude": r.lng,
            "distance_m": round(r.dist, 1) if r.dist is not None else None,
        }
        for r in rows
    ]


@router.get("/{request_id}", response_model=RequestOut)
def get_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    request = db.get(HelpRequest, request_id)
    if not request:
        raise HTTPException(404, detail="Request not found")
    return _serialize(request, user, db)


@router.patch("/{request_id}/claim", response_model=RequestOut)
def claim_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    if not user.is_volunteer:
        raise HTTPException(403, detail="Only volunteers can claim requests")

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

    # Atomic, concurrency-safe claim: only succeeds if the row is still 'open'.
    result = db.execute(
        text(
            "UPDATE help_requests "
            "SET status = 'claimed', claimed_by = :uid, claimed_at = now(), updated_at = now() "
            "WHERE id = :rid AND status = 'open' AND author_id <> :uid "
            "RETURNING id"
        ),
        {"uid": user.id, "rid": request_id},
    )
    row = result.first()
    if row is None:
        request = db.get(HelpRequest, request_id)
        if not request:
            raise HTTPException(404, detail="Request not found")
        if request.author_id == user.id:
            raise HTTPException(409, detail="You cannot claim your own request")
        if request.status != "open":
            raise HTTPException(409, detail=f"Request is not open (current status: {request.status})")
        raise HTTPException(409, detail="Request was just claimed by someone else")
    db.commit()
    request = db.get(HelpRequest, request_id)
    return _serialize(request, user, db)


@router.patch("/{request_id}/release", response_model=RequestOut)
def release_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    request = db.get(HelpRequest, request_id)
    if not request:
        raise HTTPException(404, detail="Request not found")
    if request.claimed_by != user.id:
        raise HTTPException(403, detail="Only the volunteer who claimed this request can release it")
    _transition(request, "release")
    request.claimed_by = None
    request.claimed_at = None
    request.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(request)
    return _serialize(request, user, db)


@router.patch("/{request_id}/complete", response_model=RequestOut)
def complete_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    request = db.get(HelpRequest, request_id)
    if not request:
        raise HTTPException(404, detail="Request not found")
    if request.claimed_by != user.id:
        raise HTTPException(403, detail="Only the volunteer who claimed this request can complete it")
    _transition(request, "complete")
    request.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(request)
    return _serialize(request, user, db)



@router.patch("/{request_id}/confirm", response_model=RequestOut)
def confirm_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    request = db.get(HelpRequest, request_id)
    if not request:
        raise HTTPException(404, detail="Request not found")
    if request.author_id != user.id:
        raise HTTPException(403, detail="Only the resident who created this request can confirm it")
    _transition(request, "confirm")
    request.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(request)
    return _serialize(request, user, db)


@router.patch("/{request_id}/reopen", response_model=RequestOut)
def reopen_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    """Resident marks a 'completed' request as not resolved -> back to 'open'."""
    request = db.get(HelpRequest, request_id)
    if not request:
        raise HTTPException(404, detail="Request not found")
    if request.author_id != user.id:
        raise HTTPException(403, detail="Only the resident who created this request can reopen it")
    _transition(request, "reopen")
    request.claimed_by = None
    request.claimed_at = None
    request.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(request)
    return _serialize(request, user, db)


@router.patch("/{request_id}/cancel", response_model=RequestOut)
def cancel_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpRequest:
    request = db.get(HelpRequest, request_id)
    if not request:
        raise HTTPException(404, detail="Request not found")
    if request.author_id != user.id:
        raise HTTPException(403, detail="Only the resident who created this request can cancel it")
    _transition(request, "cancel")
    request.claimed_by = None
    request.claimed_at = None
    request.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(request)
    return _serialize(request, user, db)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _transition(request: HelpRequest, action: str) -> None:
    from_states, target = TRANSITIONS[action]
    if request.status not in from_states:
        raise HTTPException(
            409,
            detail=f"Cannot {action} a request in status '{request.status}'",
        )
    request.status = target


def _serialize(request: HelpRequest, viewer: User, db: Session) -> dict:
    """Apply privacy-by-role filtering before returning a request to the client."""
    is_author = request.author_id == viewer.id
    is_claimer = request.claimed_by == viewer.id
    # Moderators get the exact address only via report review (not built yet),
    # never through the regular endpoints.
    reveal_exact = is_author or is_claimer

    geom_col = HelpRequest.location if reveal_exact else HelpRequest.approx_location
    coords = db.execute(
        select(
            _lat_expr(geom_col).label("lat"),
            _lng_expr(geom_col).label("lng"),
        ).where(HelpRequest.id == request.id)
    ).first()

    lat, lng = (coords.lat, coords.lng) if coords else (None, None)

    return {
        "id": request.id,
        "category": request.category,
        "title": request.title,
        "description": request.description,
        "status": request.status,
        "author_id": request.author_id,
        "latitude": lat,
        "longitude": lng,
        "address": request.address if reveal_exact else None,
        "claimed_by": request.claimed_by if reveal_exact else None,
        "claimed_at": request.claimed_at if reveal_exact else None,
        "created_at": request.created_at,
        "exact_location": reveal_exact,
    }

