"""Combined radius search over help requests and opportunities (PostGIS).

Requests are returned at their APPROXIMATE point and never with an address.
Hidden content, content of blocked users, past/closed opportunities and
opportunities of organizations that aren't approved are left out.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..claims import expire_unaccepted_claims
from ..database import get_db
from ..deps import get_current_user
from ..geo import lat_expr, lng_expr, point_wkt
from ..models import HelpRequest, Opportunity, OpportunitySignup, Organization, User
from ..schemas import Category, MapItem

router = APIRouter(tags=["map"])


@router.get("/map", response_model=list[MapItem])
def search_map(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(3000, ge=1, le=50000, description="metres"),
    category: Category | None = None,
    kind: Literal["all", "request", "opportunity"] = Query("all", alias="type"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    expire_unaccepted_claims(db)
    point = point_wkt(lat, lng)
    items: list[dict] = []
    if kind in ("all", "request"):
        items += _requests(db, point, radius, category)
    if kind in ("all", "opportunity"):
        items += _opportunities(db, point, radius, category)
    return sorted(items, key=lambda i: i["distance_m"])


def _requests(db: Session, point, radius: int, category: str | None) -> list[dict]:
    loc = HelpRequest.approx_location
    stmt = (
        select(
            HelpRequest.id,
            HelpRequest.category,
            HelpRequest.title,
            lat_expr(loc).label("lat"),
            lng_expr(loc).label("lng"),
            func.ST_Distance(loc, point).label("dist"),
        )
        .join(User, User.id == HelpRequest.author_id)
        .where(
            HelpRequest.status == "open",
            HelpRequest.is_hidden.is_(False),
            User.is_blocked.is_(False),
            func.ST_DWithin(loc, point, radius),
        )
    )
    if category:
        stmt = stmt.where(HelpRequest.category == category)
    return [
        _item("request", r, start_time=None, slots_left=None) for r in db.execute(stmt)
    ]


def _opportunities(db: Session, point, radius: int, category: str | None) -> list[dict]:
    loc = Opportunity.location
    taken = (
        select(func.count(OpportunitySignup.id))
        .where(OpportunitySignup.opportunity_id == Opportunity.id)
        .scalar_subquery()
    )
    stmt = (
        select(
            Opportunity.id,
            Opportunity.category,
            Opportunity.title,
            Opportunity.start_time,
            (Opportunity.slots_total - taken).label("slots_left"),
            lat_expr(loc).label("lat"),
            lng_expr(loc).label("lng"),
            func.ST_Distance(loc, point).label("dist"),
        )
        .join(Organization, Organization.id == Opportunity.organization_id)
        .join(User, User.id == Organization.user_id)
        .where(
            Opportunity.status == "open",
            Opportunity.is_hidden.is_(False),
            Opportunity.start_time > func.now(),
            Organization.verification_status == "approved",
            User.is_blocked.is_(False),
            func.ST_DWithin(loc, point, radius),
        )
    )
    if category:
        stmt = stmt.where(Opportunity.category == category)
    return [
        _item("opportunity", r, start_time=r.start_time, slots_left=r.slots_left)
        for r in db.execute(stmt)
    ]


def _item(kind: str, row, *, start_time, slots_left) -> dict:
    return {
        "type": kind,
        "id": row.id,
        "category": row.category,
        "title": row.title,
        "latitude": row.lat,
        "longitude": row.lng,
        "distance_m": round(row.dist, 1),
        "start_time": start_time,
        "slots_left": slots_left,
    }
