"""Statistics for organizations (FR 28) and the platform (FR 29)."""
from __future__ import annotations

from sqlalchemy import case, distinct, func, select, union
from sqlalchemy.orm import Session

from .models import (
    ClaimHistory,
    HelpRequest,
    Opportunity,
    OpportunitySignup,
    Organization,
    Report,
    User,
)

ACTIVE_DAYS = 30


def org_stats(db: Session, org_id: int) -> dict:
    opp = db.execute(
        select(
            func.count(Opportunity.id),
            func.count(case((Opportunity.status == "open", 1))),
            func.count(case((Opportunity.start_time <= func.now(), 1))),
        ).where(Opportunity.organization_id == org_id)
    ).one()
    signups = db.execute(
        select(
            func.count(OpportunitySignup.id),
            func.count(case((OpportunitySignup.attended.is_(True), 1))),
        )
        .join(Opportunity, Opportunity.id == OpportunitySignup.opportunity_id)
        .where(Opportunity.organization_id == org_id)
    ).one()
    return {
        "opportunities_total": opp[0],
        "opportunities_open": opp[1],
        "signups_total": signups[0],
        "attended_total": signups[1],
        "past_opportunities": opp[2],
    }


def platform_stats(db: Session) -> dict:
    since = func.now() - func.make_interval(0, 0, 0, ACTIVE_DAYS)
    # active = created a request, claimed one, or signed up recently
    active = union(
        select(HelpRequest.author_id.label("uid")).where(HelpRequest.created_at > since),
        select(ClaimHistory.volunteer_id).where(ClaimHistory.claimed_at > since),
        select(OpportunitySignup.volunteer_id).where(OpportunitySignup.signed_up_at > since),
    ).subquery()
    return {
        "requests_by_status": _count_by(db, HelpRequest.status),
        "requests_by_category": _count_by(db, HelpRequest.category),
        "users_total": db.scalar(select(func.count(User.id))),
        "active_users_30d": db.scalar(select(func.count(distinct(active.c.uid)))),
        "pending_reports": db.scalar(
            select(func.count(Report.id)).where(Report.status == "open")
        ),
        "pending_organizations": db.scalar(
            select(func.count(Organization.id)).where(
                Organization.verification_status == "pending"
            )
        ),
    }


def _count_by(db: Session, column) -> dict[str, int]:
    return dict(db.execute(select(column, func.count()).group_by(column)).all())
