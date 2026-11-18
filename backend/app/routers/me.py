"""The current user's own lists: /api/me/..."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..claims import expire_unaccepted_claims
from ..database import get_db
from ..deps import get_my_organization, require_roles
from ..models import (
    HelpRequest,
    Opportunity,
    OpportunitySignup,
    Organization,
    User,
    VerificationLog,
)
from ..privacy import serialize_request
from ..schemas import MySignupOut, OpportunityOut, OrganizationMe, OrgStats, RequestOut
from ..stats import org_stats
from .opportunities import serialize_opportunity

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/requests", response_model=list[RequestOut])
def my_requests(
    db: Session = Depends(get_db), user: User = Depends(require_roles("resident"))
) -> list[dict]:
    expire_unaccepted_claims(db)
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
    expire_unaccepted_claims(db)
    rows = db.scalars(
        select(HelpRequest)
        .where(HelpRequest.claimed_by == user.id)
        .order_by(HelpRequest.updated_at.desc())
    )
    return [serialize_request(db, r, user) for r in rows]


@router.get("/organization", response_model=OrganizationMe)
def my_organization(
    db: Session = Depends(get_db), org: Organization = Depends(get_my_organization)
) -> dict:
    comment = db.scalar(
        select(VerificationLog.comment)
        .where(VerificationLog.organization_id == org.id)
        .order_by(VerificationLog.created_at.desc(), VerificationLog.id.desc())
        .limit(1)
    )
    return {
        "id": org.id,
        "org_name": org.org_name,
        "verification_status": org.verification_status,
        "comment": comment,
    }


@router.get("/organization/stats", response_model=OrgStats)
def my_organization_stats(
    db: Session = Depends(get_db), org: Organization = Depends(get_my_organization)
) -> dict:
    return org_stats(db, org.id)


@router.get("/opportunities", response_model=list[OpportunityOut])
def my_opportunities(
    db: Session = Depends(get_db), org: Organization = Depends(get_my_organization)
) -> list[dict]:
    rows = db.scalars(
        select(Opportunity)
        .where(Opportunity.organization_id == org.id)
        .order_by(Opportunity.start_time.desc())
    )
    return [serialize_opportunity(db, o, org.user_id) for o in rows]


@router.get("/signups", response_model=list[MySignupOut])
def my_signups(
    db: Session = Depends(get_db), user: User = Depends(require_roles("volunteer"))
) -> list[dict]:
    rows = db.execute(
        select(OpportunitySignup, Opportunity, Organization)
        .join(Opportunity, Opportunity.id == OpportunitySignup.opportunity_id)
        .join(Organization, Organization.id == Opportunity.organization_id)
        .where(OpportunitySignup.volunteer_id == user.id)
        .order_by(Opportunity.start_time.desc())
    ).all()
    return [
        {
            "id": s.id,
            "opportunity": {
                "id": o.id,
                "title": o.title,
                "start_time": o.start_time,
                "status": o.status,
                "organization": {"id": org.id, "org_name": org.org_name},
            },
            "signed_up_at": s.signed_up_at,
            "attended": s.attended,
        }
        for s, o, org in rows
    ]
