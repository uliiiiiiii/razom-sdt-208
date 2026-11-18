"""Moderator-only routes: reports, organization verification, users, access log."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import (
    AddressAccess,
    HelpRequest,
    Opportunity,
    Organization,
    Report,
    User,
    VerificationLog,
)
from ..moderation_rules import (
    hidden_automatically,
    load_target,
    open_report_count,
    owner_of,
    resolve_reports,
    set_hidden,
)
from ..privacy import serialize_request
from ..schemas import (
    AccessLogEntry,
    OrganizationAdmin,
    OrgDecision,
    OrgStats,
    PlatformStats,
    ReportDecision,
    ReportDetail,
    ReportOut,
    RequestOut,
    OpportunityOut,
    VisibilityUpdate,
    UserAdmin,
    UserUpdate,
)
from ..stats import org_stats, platform_stats
from .opportunities import serialize_opportunity

router = APIRouter(
    prefix="/moderation",
    tags=["moderation"],
    dependencies=[Depends(require_roles("moderator"))],
)
moderator = require_roles("moderator")


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------
@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    status: Literal["open", "dismissed", "actioned"] = "open",
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(Report, User)
        .join(User, User.id == Report.reporter_id)
        .where(Report.status == status)
        .order_by(Report.created_at.desc(), Report.id.desc())
    ).all()
    return [_report_out(db, r, u) for r, u in rows]


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: int, db: Session = Depends(get_db), mod: User = Depends(moderator)
) -> dict:
    report = _get_report(db, report_id)
    out = _report_out(db, report, db.get(User, report.reporter_id))
    out["target"] = _target_out(db, report, mod)
    return out


@router.patch("/reports/{report_id}", response_model=ReportOut)
def decide_report(
    report_id: int,
    payload: ReportDecision,
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
) -> dict:
    report = _get_report(db, report_id)
    if report.status != "open":
        raise HTTPException(409, detail="This report has already been resolved")
    target = load_target(db, report.target_type, report.target_id)
    if target is None:
        raise HTTPException(404, detail="Reported item no longer exists")

    if payload.decision == "dismiss":
        # nothing wrong: undo the 3-reports auto-hide, never a moderator's decision
        if hidden_automatically(target):
            set_hidden(db, target, False)
        outcome = "dismissed"
    elif payload.decision == "hide":
        if isinstance(target, User):
            raise HTTPException(400, detail="A user can't be hidden; block them instead")
        set_hidden(db, target, True)
        outcome = "actioned"
    else:  # block the user, or the author/owner of the reported content
        owner = owner_of(db, target)
        if owner.id == mod.id:
            raise HTTPException(400, detail="You can't block yourself")
        set_hidden(db, owner, True)
        outcome = "actioned"
    resolve_reports(db, report.target_type, report.target_id, outcome)
    db.commit()
    db.refresh(report)
    return _report_out(db, report, db.get(User, report.reporter_id))


# ---------------------------------------------------------------------------
# hide / unhide content directly
# ---------------------------------------------------------------------------
@router.patch("/requests/{request_id}", response_model=RequestOut)
def set_request_visibility(
    request_id: int,
    payload: VisibilityUpdate,
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
) -> dict:
    req = db.get(HelpRequest, request_id)
    if req is None:
        raise HTTPException(404, detail="Request not found")
    set_hidden(db, req, payload.is_hidden)
    db.commit()
    db.refresh(req)
    return serialize_request(db, req, mod)


@router.patch("/opportunities/{opp_id}", response_model=OpportunityOut)
def set_opportunity_visibility(
    opp_id: int,
    payload: VisibilityUpdate,
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
) -> dict:
    opp = db.get(Opportunity, opp_id)
    if opp is None:
        raise HTTPException(404, detail="Opportunity not found")
    set_hidden(db, opp, payload.is_hidden)
    db.commit()
    db.refresh(opp)
    return serialize_opportunity(db, opp, mod.id)


# ---------------------------------------------------------------------------
# organizations
# ---------------------------------------------------------------------------
@router.get("/organizations", response_model=list[OrganizationAdmin])
def list_organizations(
    status: Literal["pending", "approved", "rejected"] = "pending",
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(Organization, User)
        .join(User, User.id == Organization.user_id)
        .where(Organization.verification_status == status)
        .order_by(Organization.created_at)
    ).all()
    return [_org_out(o, u) for o, u in rows]


@router.patch("/organizations/{org_id}", response_model=OrganizationAdmin)
def decide_organization(
    org_id: int,
    payload: OrgDecision,
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
) -> dict:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, detail="Organization not found")
    org.verification_status = payload.decision
    org.verified_at = datetime.now(timezone.utc)
    org.verified_by = mod.id
    db.add(
        VerificationLog(
            organization_id=org.id,
            moderator_id=mod.id,
            decision=payload.decision,
            comment=payload.comment,
        )
    )
    db.commit()
    return _org_out(org, db.get(User, org.user_id))


@router.get("/organizations/{org_id}/stats", response_model=OrgStats)
def organization_stats(org_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(Organization, org_id) is None:
        raise HTTPException(404, detail="Organization not found")
    return org_stats(db, org_id)


@router.get("/stats", response_model=PlatformStats)
def stats(db: Session = Depends(get_db)) -> dict:
    return platform_stats(db)


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
@router.get("/users", response_model=list[UserAdmin])
def search_users(q: str = "", db: Session = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc()).limit(50)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.display_name.ilike(like)))
    return list(db.scalars(stmt))


@router.patch("/users/{user_id}", response_model=UserAdmin)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    mod: User = Depends(moderator),
) -> User:
    if user_id == mod.id:
        raise HTTPException(400, detail="You can't change your own moderator or blocked status")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail="User not found")
    changes = payload.model_dump(exclude_none=True)
    if "is_blocked" in changes:
        set_hidden(db, user, changes.pop("is_blocked"))  # also releases their claims
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# address access audit
# ---------------------------------------------------------------------------
@router.get("/access-log", response_model=list[AccessLogEntry])
def access_log(request_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = (
        select(AddressAccess, User)
        .join(User, User.id == AddressAccess.user_id)
        .order_by(AddressAccess.accessed_at.desc())
        .limit(200)
    )
    if request_id is not None:
        stmt = stmt.where(AddressAccess.request_id == request_id)
    return [
        {
            "request_id": a.request_id,
            "user": {"id": u.id, "display_name": u.display_name},
            "via": a.via,
            "accessed_at": a.accessed_at,
        }
        for a, u in db.execute(stmt).all()
    ]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _get_report(db: Session, report_id: int) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404, detail="Report not found")
    return report


def _report_out(db: Session, report: Report, reporter: User) -> dict:
    return {
        "id": report.id,
        "target_type": report.target_type,
        "target_id": report.target_id,
        "reason": report.reason,
        "status": report.status,
        "created_at": report.created_at,
        "reporter": {"id": reporter.id, "display_name": reporter.display_name},
        "open_reports_on_target": open_report_count(db, report.target_type, report.target_id),
    }


def _target_out(db: Session, report: Report, mod: User) -> dict | None:
    target = load_target(db, report.target_type, report.target_id)
    if target is None:
        return None
    if isinstance(target, HelpRequest):
        # exact address only while the report is open; the reveal is logged
        via = "report_review" if report.status == "open" else None
        return serialize_request(db, target, mod, via=via)
    if isinstance(target, User):
        return {
            "id": target.id,
            "display_name": target.display_name,
            "roles": target.roles,
            "is_blocked": target.is_blocked,
        }
    return serialize_opportunity(db, target, mod.id)


def _org_out(org: Organization, user: User) -> dict:
    return {
        "id": org.id,
        "org_name": org.org_name,
        "verification_status": org.verification_status,
        "created_at": org.created_at,
        "user": user,
    }
