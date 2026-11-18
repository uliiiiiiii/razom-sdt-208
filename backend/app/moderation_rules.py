"""Shared rules for reports: resolving targets, auto-hide, restore.

A report targets a help request, an opportunity or a user. "Hiding" a user
means blocking (suspending) them: they can't log in and their tokens stop
working, and their claimed requests go back to the map.

Hides/blocks made by the 3-reports rule are flagged (auto_hidden /
auto_blocked) so that a moderator dismissing the reports undoes only those,
never a moderator's own decision. Moderators are never auto-suspended, so
three fake accounts can't lock the moderators out.
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .claims import release_claims_of
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


def set_hidden(db: Session, target: Target, hidden: bool, *, auto: bool = False) -> None:
    if isinstance(target, User):
        target.is_blocked = hidden
        target.auto_blocked = hidden and auto
        if hidden:
            release_claims_of(db, target.id)
    else:
        target.is_hidden = hidden
        target.auto_hidden = hidden and auto


def is_hidden(target: Target) -> bool:
    return target.is_blocked if isinstance(target, User) else target.is_hidden


def hidden_automatically(target: Target) -> bool:
    return target.auto_blocked if isinstance(target, User) else target.auto_hidden


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
    target = load_target(db, target_type, target_id)
    if is_hidden(target) or (isinstance(target, User) and target.is_moderator):
        return False  # already handled by a moderator / never auto-suspend moderators
    set_hidden(db, target, True, auto=True)
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
