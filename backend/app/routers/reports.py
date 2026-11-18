"""Any logged-in user can report a request, an opportunity or a user (FR 24)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Report, User
from ..moderation_rules import apply_auto_hide, load_target, owner_of
from ..ratelimit import REPORT_LIMIT, limiter
from ..schemas import ReportCreate, ReportCreated

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportCreated, status_code=status.HTTP_201_CREATED)
@limiter.limit(REPORT_LIMIT)
def create_report(
    request: Request,
    payload: ReportCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Report:
    target = load_target(db, payload.target_type, payload.target_id, lock=True)
    if target is None:
        raise HTTPException(404, detail="Reported item not found")
    if owner_of(db, target).id == user.id:
        raise HTTPException(400, detail="You cannot report yourself or your own content")
    duplicate = db.scalar(
        select(Report.id).where(
            Report.reporter_id == user.id,
            Report.target_type == payload.target_type,
            Report.target_id == payload.target_id,
        )
    )
    if duplicate:
        raise HTTPException(409, detail="You have already reported this")
    report = Report(
        reporter_id=user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason,
    )
    db.add(report)
    db.flush()
    apply_auto_hide(db, payload.target_type, payload.target_id)
    db.commit()
    db.refresh(report)
    return report
