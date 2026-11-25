"""Demo data for local development: a lived-in Kyiv map plus accounts in
every state, so each screen and flow has something to show.

    python -m app.demo_seed    # re-run before a demo: it wipes and seeds again

DEVELOPMENT ONLY: every account shares a published password. Each run wipes
the database first, so it refuses to run on one that has any non-demo user.

The data obeys the app's own rules (3 active requests per resident, 2 claims
per volunteer, claim expiry...), so every demo flow behaves like the real one.
"""
from __future__ import annotations

import random
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import Base
from .geo import point_wkt, round_location
from .models import (
    ClaimHistory,
    HelpRequest,
    Opportunity,
    OpportunitySignup,
    Organization,
    Report,
    User,
    VerificationLog,
)
from .security import hash_password

DEMO_PASSWORD = "demo-pass-123"
DEMO_DOMAIN = "@razom.demo"
DEMO_ACCOUNTS = {
    "resident@razom.demo": ("Olena (resident)", {"is_resident": True}),
    "volunteer@razom.demo": ("Taras (volunteer)", {"is_volunteer": True}),
    "org@razom.demo": ("Sirius Shelter", {"is_organization": True}),
    "pending-org@razom.demo": ("New Charity", {"is_organization": True}),
    "rejected-org@razom.demo": ("Fake Fund", {"is_organization": True}),
    "moderator@razom.demo": ("Moderator", {"is_moderator": True}),
    "blocked@razom.demo": ("Blocked user", {"is_resident": True}),
}
GENERATED_RESIDENTS = 15  # resident2..resident16
GENERATED_VOLUNTEERS = 4  # volunteer2..volunteer5
GENERATED_REQUESTS = 40

DISTRICTS = {
    "Podil": (50.4650, 30.5150),
    "Pechersk": (50.4350, 30.5450),
    "Shevchenkivskyi": (50.4550, 30.4900),
    "Obolon": (50.5050, 30.4980),
    "Solomianskyi": (50.4300, 30.4550),
    "Holosiivskyi": (50.3950, 30.5100),
    "Darnytskyi": (50.4200, 30.6300),
    "Desnianskyi": (50.5050, 30.6000),
}
TEMPLATES = {
    "charging": [
        ("Need a power bank charged", "No light for 30 hours. Phone and power bank are dead and I can't reach an Invincibility Point."),
        ("Charge a medical device battery", "My father's oxygen concentrator battery needs charging before the evening outage."),
        ("Phone charge for an elderly neighbour", "She can't call her daughter. One charge would be enough."),
    ],
    "groceries": [
        ("Bread and milk, please", "I'm 82 and the shop is too far to walk with my knees. I'll pay back in cash."),
        ("Groceries for a family with a newborn", "Baby formula, buckwheat and some vegetables. We can't leave the flat."),
        ("Small grocery run", "Tinned food and tea. The lift is not working and I live on the 12th floor."),
    ],
    "medicine": [
        ("Pick up insulin from the pharmacy", "Prescription is ready at the pharmacy nearby. I can't leave home during the blackout."),
        ("Blood pressure pills", "My supply runs out tomorrow. The pharmacy two streets away has them in stock."),
    ],
    "water": [
        ("Drinking water for a 9th-floor flat", "The lift is down and the pumps don't work. Two 6-litre bottles would help a lot."),
        ("Water for an elderly couple", "We can't carry water up the stairs. Any amount helps."),
        ("Refill water canisters", "Two empty 10-litre canisters, the water point is 1 km away."),
    ],
    "transport": [
        ("Lift to the hospital for a check-up", "Appointment at 10:00. Taxis aren't coming to our district today."),
        ("Help getting to the shelter with a wheelchair", "I need someone to help me down the stairs during alarms."),
    ],
    "pets": [
        ("Walk my dog for a few days", "I'm recovering from surgery. The dog is calm and friendly."),
        ("Cat food delivery", "Two cats and the pet shop is closed in our area. Any dry food works."),
    ],
    "other": [
        ("Help covering a broken window", "The blast wave broke a window. I have plastic film but can't do it alone."),
        ("Carry firewood up to the flat", "Wood is delivered to the yard, I need help carrying it to the 4th floor."),
    ],
}

Scenario = Callable[[Session, dict], None]


def generated_requests() -> list[dict]:
    """The map's volume: deterministic (fixed seed), round-robin authors so no
    resident has more than 3 active requests, a third posted in the last 6 h."""
    rng = random.Random(208)
    categories = sorted(TEMPLATES)
    districts = list(DISTRICTS.values())
    out = []
    for i in range(GENERATED_REQUESTS):
        category = categories[i % len(categories)]
        title, description = rng.choice(TEMPLATES[category])
        lat0, lng0 = districts[i % len(districts)]
        out.append({
            "author_index": i % GENERATED_RESIDENTS,
            "category": category,
            "title": title,
            "description": description,
            "lat": round(lat0 + rng.uniform(-0.012, 0.012), 6),
            "lng": round(lng0 + rng.uniform(-0.018, 0.018), 6),
            "address": f"Demo street {i + 1}, apt {rng.randint(1, 120)}",
            "age_hours": rng.uniform(0.5, 6) if i % 3 == 0 else rng.uniform(6, 120),
        })
    return out


def _all_accounts() -> dict[str, tuple[str, dict]]:
    accounts = dict(DEMO_ACCOUNTS)
    for n in range(2, GENERATED_RESIDENTS + 2):
        accounts[f"resident{n}{DEMO_DOMAIN}"] = (f"Resident {n}", {"is_resident": True})
    for n in range(2, GENERATED_VOLUNTEERS + 2):
        accounts[f"volunteer{n}{DEMO_DOMAIN}"] = (f"Volunteer {n}", {"is_volunteer": True})
    return accounts


def new_request(author: User, category: str, title: str, lat: float, lng: float,
                address: str, created: datetime, **fields) -> HelpRequest:
    return HelpRequest(
        author_id=author.id, category=category, title=title,
        description=fields.pop("description", title + "."),
        location=point_wkt(lat, lng), approx_location=point_wkt(*round_location(lat, lng)),
        address=address, created_at=created, updated_at=created, **fields,
    )


def _accounts(db: Session, ctx: dict) -> None:
    password_hash = hash_password(DEMO_PASSWORD)
    ctx["users"] = {
        email: User(email=email, password_hash=password_hash, display_name=name, **flags)
        for email, (name, flags) in _all_accounts().items()
    }
    db.add_all(ctx["users"].values())
    db.flush()


def _map_requests(db: Session, ctx: dict) -> None:
    users, now = ctx["users"], ctx["now"]
    ctx["generated"] = []
    for r in generated_requests():
        author = users[f"resident{r['author_index'] + 2}{DEMO_DOMAIN}"]
        req = new_request(author, r["category"], r["title"], r["lat"], r["lng"], r["address"],
                          now - timedelta(hours=r["age_hours"]), description=r["description"])
        db.add(req)
        ctx["generated"].append(req)
    db.flush()


def _claim(req: HelpRequest, volunteer: User, claimed_at: datetime, outcome: str,
           accepted: bool) -> tuple[HelpRequest, int, datetime, str]:
    """Sets the claim fields (before insert: the DB rejects a claimed request
    without a claimer) and remembers the matching claim_history row."""
    req.claimed_by, req.claimed_at = volunteer.id, claimed_at
    req.accepted_at = claimed_at + timedelta(minutes=10) if accepted else None
    return req, volunteer.id, claimed_at, outcome


def _resident_journey(db: Session, ctx: dict) -> None:
    """resident@ has one request in each state; volunteer@ holds the matching
    claims (2 'claimed': the cap) and has helped once before."""
    users, now = ctx["users"], ctx["now"]
    res, vol = users["resident@razom.demo"], users["volunteer@razom.demo"]
    h, d = (lambda n: timedelta(hours=n)), (lambda n: timedelta(days=n))
    rows = {
        "open": new_request(res, "charging", "Need a power bank charged", 50.4501, 30.5234,
                            "Khreshchatyk 1, apt 5", now - h(2)),
        "claimed": new_request(res, "medicine", "Pick up insulin from the pharmacy", 50.4420, 30.5110,
                               "Velyka Vasylkivska 10, apt 2", now - h(3), status="claimed"),
        "completed": new_request(res, "water", "Drinking water for a 9th-floor flat", 50.4480, 30.5190,
                                 "Khreshchatyk 1, apt 5", now - d(4), status="completed"),
        "confirmed": new_request(res, "groceries", "Bread and milk, please", 50.4490, 30.5200,
                                 "Khreshchatyk 1, apt 5", now - d(12), status="confirmed",
                                 closed_at=now - d(10)),
        "cancelled": new_request(res, "transport", "Lift to the hospital for a check-up", 50.4510, 30.5220,
                                 "Khreshchatyk 1, apt 5", now - d(3), status="cancelled",
                                 closed_at=now - d(2)),
        # volunteer@'s accepted claim: they see this address
        "accepted": new_request(users["resident12@razom.demo"], "pets", "Walk my dog for a few days",
                                50.4620, 30.5080, "Kyrylivska 40, apt 17", now - h(5), status="claimed"),
    }
    claimed = [
        _claim(rows["claimed"], vol, now - h(1), "active", accepted=False),  # < 12 h: doesn't expire
        _claim(rows["completed"], vol, now - d(3), "completed", accepted=True),
        _claim(rows["confirmed"], vol, now - d(11), "completed", accepted=True),
        _claim(rows["accepted"], vol, now - timedelta(minutes=30), "active", accepted=True),
    ]
    db.add_all(rows.values())
    db.flush()
    for req, volunteer_id, claimed_at, outcome in claimed:
        db.add(ClaimHistory(request_id=req.id, volunteer_id=volunteer_id,
                            claimed_at=claimed_at, outcome=outcome))


def _moderation_queue(db: Session, ctx: dict) -> None:
    """A request auto-hidden by 3 reports, a reported user below the threshold,
    and an account a moderator blocked."""
    users = ctx["users"]
    target = ctx["generated"][5]
    for n in (2, 3, 4):
        db.add(Report(reporter_id=users[f"volunteer{n}{DEMO_DOMAIN}"].id, target_type="request",
                      target_id=target.id, reason="Asks for money transfers in the description"))
    target.is_hidden = target.auto_hidden = True
    db.add(Report(reporter_id=users["volunteer5@razom.demo"].id, target_type="user",
                  target_id=users["resident5@razom.demo"].id, reason="Was rude when I arrived"))
    users["blocked@razom.demo"].is_blocked = True


def _organizations(db: Session, ctx: dict) -> None:
    """Approved (with a full and a past offer), pending and rejected."""
    users, now = ctx["users"], ctx["now"]
    moderator = users["moderator@razom.demo"]
    approved = Organization(
        user_id=users["org@razom.demo"].id, org_name="Sirius Shelter",
        verification_status="approved", verified_at=now, verified_by=moderator.id,
    )
    rejected = Organization(
        user_id=users["rejected-org@razom.demo"].id, org_name="Fake Fund",
        verification_status="rejected", verified_at=now, verified_by=moderator.id,
    )
    db.add_all([approved, rejected,
                Organization(user_id=users["pending-org@razom.demo"].id, org_name="New Charity")])
    db.flush()
    db.add(VerificationLog(organization_id=rejected.id, moderator_id=moderator.id,
                           decision="rejected", comment="Could not confirm the registration number."))
    offers = {}
    for key, title, category, days, slots, lat, lng in (
        ("dogs", "Walk the shelter dogs", "pets", 2, 5, 50.4600, 30.5000),
        ("food", "Sort donated food", "groceries", 5, 5, 50.4550, 30.5300),
        ("full", "Pack hygiene kits", "other", 3, 2, 50.4400, 30.5200),
        ("past", "Clean the shelter yard", "pets", -1, 5, 50.4600, 30.5000),
    ):
        offers[key] = Opportunity(
            organization_id=approved.id, title=title, category=category, description=title,
            location=point_wkt(lat, lng), start_time=now + timedelta(days=days), slots_total=slots,
        )
    db.add_all(offers.values())
    db.flush()
    for key, email in (("dogs", "volunteer@razom.demo"), ("past", "volunteer@razom.demo"),
                       ("full", "volunteer2@razom.demo"), ("full", "volunteer3@razom.demo")):
        db.add(OpportunitySignup(opportunity_id=offers[key].id, volunteer_id=users[email].id))


SCENARIOS: list[Scenario] = [
    _accounts,
    _map_requests,
    _resident_journey,
    _moderation_queue,
    _organizations,
]


def seed_demo(db: Session) -> None:
    """Wipes the database and seeds it fresh, so a re-run always restores a
    working demo (waiting claims expire after 12 h, "fresh" requests age).
    Allowed only because every user is a demo user."""
    if db.scalar(select(User.id).where(User.email.not_like(f"%{DEMO_DOMAIN}")).limit(1)):
        raise RuntimeError("Refusing to seed demo data: the database has real (non-demo) users")
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    ctx: dict = {"now": datetime.now(timezone.utc)}
    for scenario in SCENARIOS:
        scenario(db, ctx)
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
    print(f"  plus resident2-{GENERATED_RESIDENTS + 1} and volunteer2-{GENERATED_VOLUNTEERS + 1}{DEMO_DOMAIN}")
