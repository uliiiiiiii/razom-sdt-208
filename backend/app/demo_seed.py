"""Demo data for local development: one account per role plus some content.

    python -m app.demo_seed

DEVELOPMENT ONLY: every account shares a published password. The script
refuses to run on a database that already has non-demo users.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .geo import point_wkt, round_location
from .models import HelpRequest, Opportunity, Organization, User
from .security import hash_password

DEMO_PASSWORD = "demo-pass-123"
DEMO_ACCOUNTS = {
    "resident@razom.demo": ("Olena (resident)", {"is_resident": True}),
    "volunteer@razom.demo": ("Taras (volunteer)", {"is_volunteer": True}),
    "org@razom.demo": ("Sirius Shelter", {"is_organization": True}),
    "pending-org@razom.demo": ("New Charity", {"is_organization": True}),
    "moderator@razom.demo": ("Moderator", {"is_moderator": True}),
}


def seed_demo(db: Session) -> None:
    demo_emails = list(DEMO_ACCOUNTS)
    others = db.scalar(select(func.count(User.id)).where(User.email.not_in(demo_emails)))
    if others:
        raise RuntimeError("Refusing to seed demo data: the database has real (non-demo) users")
    if db.scalar(select(User.id).where(User.email == demo_emails[0])):
        return  # already seeded

    password_hash = hash_password(DEMO_PASSWORD)
    users = {}
    for email, (name, flags) in DEMO_ACCOUNTS.items():
        users[email] = User(email=email, password_hash=password_hash, display_name=name, **flags)
        db.add(users[email])
    db.flush()

    resident = users["resident@razom.demo"]
    for category, title, lat, lng, address in (
        ("charging", "Need a power bank charged", 50.4501, 30.5234, "Khreshchatyk 1, apt 5"),
        ("medicine", "Pick up insulin from the pharmacy", 50.4420, 30.5110, "Velyka Vasylkivska 10, apt 2"),
    ):
        approx = round_location(lat, lng)
        db.add(
            HelpRequest(
                author_id=resident.id, category=category, title=title,
                description=title + ". I can't leave home during the blackout.",
                location=point_wkt(lat, lng), approx_location=point_wkt(*approx), address=address,
            )
        )

    now = datetime.now(timezone.utc)
    approved = Organization(
        user_id=users["org@razom.demo"].id, org_name="Sirius Shelter",
        verification_status="approved", verified_at=now,
        verified_by=users["moderator@razom.demo"].id,
    )
    db.add(approved)
    db.add(Organization(user_id=users["pending-org@razom.demo"].id, org_name="New Charity"))
    db.flush()
    for title, days, lat, lng in (
        ("Walk the shelter dogs", 2, 50.4600, 30.5000),
        ("Sort donated food", 5, 50.4550, 30.5300),
    ):
        db.add(
            Opportunity(
                organization_id=approved.id, title=title, category="pets" if "dogs" in title else "groceries",
                description=title, location=point_wkt(lat, lng),
                start_time=now + timedelta(days=days), slots_total=5,
            )
        )
    db.commit()


if __name__ == "__main__":
    from .config import settings
    from .database import SessionLocal
    from .migrate import upgrade_to_head

    upgrade_to_head(settings.database_url)  # works even before the server ever ran
    with SessionLocal() as session:
        try:
            seed_demo(session)
        except RuntimeError as exc:
            sys.exit(str(exc))
    print(f"Demo accounts (password: {DEMO_PASSWORD}):")
    for email, (name, _) in DEMO_ACCOUNTS.items():
        print(f"  {email:26} {name}")
