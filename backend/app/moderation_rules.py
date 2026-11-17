"""Shared rules for reports: resolving targets, auto-hide, restore.

A report targets a help request, an opportunity or a user. "Hiding" a user
means blocking (suspending) them: they can't log in and their tokens stop
working.
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .models import HelpRequest, Opportunity, Organization, Report, User

AUTO_HIDE_THRESHOLD = 3  # distinct open reports on one target

Target = HelpRequest | Opportunity | User
_MODELS = {"request": HelpRequest, "opportunity": Opportunity, "user": User}


def load_target(
    db: Session, target_type: str, target_id: int, *, lock: bool = False
) -> Target | None:
    """lock=True holds the row until commit, so concurrent reports on the same
    target are counted one after another (no missed auto-hide)."""
    return db.get(_MODELS[target_type], target_id, with_for_update=lock)


def owner_of(db: Session, target: Target) -> User:
    if isinstance(target, HelpRequest):
        return target.author
    if isinstance(target, Opportunity):
        org = db.get(Organization, target.organization_id)
        return db.get(User, org.user_id)
    return target


def set_hidden(target: Target, hidden: bool) -> None:
    if isinstance(target, User):
        target.is_blocked = hidden
    else:
        target.is_hidden = hidden


def open_report_count(db: Session, target_type: str, target_id: int) -> int:
    return db.scalar(
        select(func.count(Report.id)).where(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.status == "open",
        )
    ) or 0


def apply_auto_hide(db: Session, target_type: str, target_id: int) -> bool:
    """Hide/suspend the target once it has AUTO_HIDE_THRESHOLD open reports.
    Reporters are distinct by the reports table's unique constraint."""
    if open_report_count(db, target_type, target_id) < AUTO_HIDE_THRESHOLD:
        return False
    set_hidden(load_target(db, target_type, target_id), True)
    return True


def resolve_reports(db: Session, target_type: str, target_id: int, status: str) -> None:
    """Close every open report on the target with the same outcome."""
    db.execute(
        update(Report)
        .where(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.status == "open",
        )
        .values(status=status)
    )
