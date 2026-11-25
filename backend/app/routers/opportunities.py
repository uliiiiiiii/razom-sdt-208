"""Opportunities published by verified organizations, and volunteer sign-ups."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_roles, require_verified_org
from ..geo import point_wkt
from ..models import Opportunity, OpportunitySignup, Organization, User
from ..schemas import (
    AttendanceUpdate,
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    SignupOut,
)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

NOT_FOUND = "Opportunity not found"


@router.post("", response_model=OpportunityOut, status_code=status.HTTP_201_CREATED)
def create_opportunity(
    payload: OpportunityCreate,
    db: Session = Depends(get_db),
    org: Organization = Depends(require_verified_org),
) -> dict:
    opp = Opportunity(
        organization_id=org.id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        location=point_wkt(payload.latitude, payload.longitude),
        start_time=payload.start_time,
        slots_total=payload.slots_total,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return serialize_opportunity(db, opp, org.user_id)


@router.get("/{opp_id}", response_model=OpportunityOut)
def get_opportunity(
    opp_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    opp = db.get(Opportunity, opp_id)
    if not opp or not opportunity_visible_to(db, opp, user.id):
        raise HTTPException(404, detail=NOT_FOUND)
    return serialize_opportunity(db, opp, user.id)


@router.patch("/{opp_id}", response_model=OpportunityOut)
def update_opportunity(
    opp_id: int,
    payload: OpportunityUpdate,
    db: Session = Depends(get_db),
    org: Organization = Depends(require_verified_org),
) -> dict:
    opp = _get_owned(db, opp_id, org)
    # null means "leave unchanged" (NOT NULL columns can't be cleared)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "slots_total" in changes and changes["slots_total"] < _slots_taken(db, opp.id):
        raise HTTPException(409, detail="slots_total cannot be lower than the number of sign-ups")
    lat, lng = changes.pop("latitude", None), changes.pop("longitude", None)
    if (lat is None) != (lng is None):
        raise HTTPException(400, detail="latitude and longitude must be changed together")
    if lat is not None:
        opp.location = point_wkt(lat, lng)
    for field, value in changes.items():
        setattr(opp, field, value)
    db.commit()
    db.refresh(opp)
    return serialize_opportunity(db, opp, org.user_id)


@router.patch("/{opp_id}/close", response_model=OpportunityOut)
def close_opportunity(
    opp_id: int,
    db: Session = Depends(get_db),
    org: Organization = Depends(require_verified_org),
) -> dict:
    opp = _get_owned(db, opp_id, org)
    opp.status = "closed"
    db.commit()
    db.refresh(opp)
    return serialize_opportunity(db, opp, org.user_id)


@router.post("/{opp_id}/signups", response_model=SignupOut, status_code=status.HTTP_201_CREATED)
def sign_up(
    opp_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("volunteer")),
) -> dict:
    # lock the opportunity so two volunteers can't both take the last slot
    opp = db.scalar(select(Opportunity).where(Opportunity.id == opp_id).with_for_update())
    if not opp or not opportunity_visible_to(db, opp, user.id):
        raise HTTPException(404, detail=NOT_FOUND)
    if opp.status != "open":
        raise HTTPException(409, detail="Opportunity is closed")
    if opp.start_time <= _now():
        raise HTTPException(409, detail="Opportunity has already started")
    if _find_signup(db, opp_id, user.id):
        raise HTTPException(409, detail="You are already signed up")
    if _slots_taken(db, opp_id) >= opp.slots_total:
        raise HTTPException(409, detail="No free slots left")
    signup = OpportunitySignup(opportunity_id=opp_id, volunteer_id=user.id)
    db.add(signup)
    db.commit()
    db.refresh(signup)
    return _serialize_signup(signup, user)


@router.delete("/{opp_id}/signups/me", status_code=status.HTTP_204_NO_CONTENT)
def cancel_sign_up(
    opp_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("volunteer")),
) -> Response:
    signup = _find_signup(db, opp_id, user.id)
    if not signup:
        raise HTTPException(404, detail="You are not signed up")
    if db.get(Opportunity, opp_id).start_time <= _now():
        raise HTTPException(409, detail="Opportunity has already started")
    db.delete(signup)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{opp_id}/signups", response_model=list[SignupOut])
def list_sign_ups(
    opp_id: int,
    db: Session = Depends(get_db),
    org: Organization = Depends(require_verified_org),
) -> list[dict]:
    _get_owned(db, opp_id, org)
    rows = db.execute(
        select(OpportunitySignup, User)
        .join(User, User.id == OpportunitySignup.volunteer_id)
        .where(OpportunitySignup.opportunity_id == opp_id)
        .order_by(OpportunitySignup.signed_up_at)
    ).all()
    return [_serialize_signup(s, u) for s, u in rows]


@router.patch("/{opp_id}/signups/{signup_id}", response_model=SignupOut)
def mark_attendance(
    opp_id: int,
    signup_id: int,
    payload: AttendanceUpdate,
    db: Session = Depends(get_db),
    org: Organization = Depends(require_verified_org),
) -> dict:
    opp = _get_owned(db, opp_id, org)
    signup = db.get(OpportunitySignup, signup_id)
    if not signup or signup.opportunity_id != opp_id:
        raise HTTPException(404, detail="Sign-up not found")
    if opp.start_time > _now():
        raise HTTPException(409, detail="Attendance can be marked only after the start time")
    signup.attended = payload.attended
    db.commit()
    return _serialize_signup(signup, db.get(User, signup.volunteer_id))


# ---------------------------------------------------------------------------
# helpers (serialize_opportunity is also used by /api/me)
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def opportunity_visible_to(db: Session, opp: Opportunity, viewer_id: int) -> bool:
    """The owner always sees it; others only if it isn't hidden, the organization
    is approved and its account isn't blocked (same rules as the map)."""
    org = db.get(Organization, opp.organization_id)
    if org.user_id == viewer_id:
        return True
    owner = db.get(User, org.user_id)
    return not opp.is_hidden and org.verification_status == "approved" and not owner.is_blocked


def _get_owned(db: Session, opp_id: int, org: Organization) -> Opportunity:
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(404, detail=NOT_FOUND)
    if opp.organization_id != org.id:
        raise HTTPException(403, detail="Only the organization that published this can manage it")
    return opp


def _slots_taken(db: Session, opp_id: int) -> int:
    return db.scalar(
        select(func.count(OpportunitySignup.id)).where(OpportunitySignup.opportunity_id == opp_id)
    ) or 0


def _find_signup(db: Session, opp_id: int, volunteer_id: int) -> OpportunitySignup | None:
    return db.scalar(
        select(OpportunitySignup).where(
            OpportunitySignup.opportunity_id == opp_id,
            OpportunitySignup.volunteer_id == volunteer_id,
        )
    )


def _serialize_signup(signup: OpportunitySignup, volunteer: User) -> dict:
    return {
        "id": signup.id,
        "volunteer": {"id": volunteer.id, "display_name": volunteer.display_name},
        "signed_up_at": signup.signed_up_at,
        "attended": signup.attended,
    }


def serialize_opportunity(db: Session, opp: Opportunity, viewer_id: int) -> dict:
    org = db.get(Organization, opp.organization_id)
    return {
        "id": opp.id,
        "organization": {"id": org.id, "org_name": org.org_name},
        "title": opp.title,
        "description": opp.description,
        "category": opp.category,
        "latitude": opp.lat,
        "longitude": opp.lng,
        "start_time": opp.start_time,
        "slots_total": opp.slots_total,
        "slots_taken": opp.slots_taken,
        "status": opp.status,
        "is_signed_up": _find_signup(db, opp.id, viewer_id) is not None,
        "is_owner": org.user_id == viewer_id,
        "is_hidden": opp.is_hidden,
    }
