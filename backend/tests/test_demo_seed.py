from collections import Counter

import pytest

from app.demo_seed import DEMO_ACCOUNTS, DEMO_PASSWORD, generated_requests, seed_demo
from app.models import User
from app.security import hash_password
from conftest import make_user

CATEGORIES = {"charging", "groceries", "medicine", "water", "transport", "pets", "other"}


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, email
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_seed_creates_one_account_per_role(client, db):
    seed_demo(db)
    roles = {
        email: client.get("/api/auth/me", headers=login(client, email)).json()["roles"]
        for email in ("resident@razom.demo", "volunteer@razom.demo", "moderator@razom.demo")
    }
    assert roles["resident@razom.demo"] == ["resident"]
    assert roles["volunteer@razom.demo"] == ["volunteer"]
    assert roles["moderator@razom.demo"] == ["moderator"]
    pending = client.get("/api/me/organization", headers=login(client, "pending-org@razom.demo")).json()
    assert pending["verification_status"] == "pending"


def test_generated_requests_are_deterministic_and_varied():
    reqs = generated_requests()
    assert reqs == generated_requests()
    assert len(reqs) == 40
    assert {r["category"] for r in reqs} == CATEGORIES
    assert max(Counter(r["author_index"] for r in reqs).values()) <= 3
    assert sum(r["age_hours"] < 6 for r in reqs) >= 13


def test_seed_fills_the_map(client, db):
    seed_demo(db)
    items = client.get(
        "/api/map",
        params={"lat": 50.45, "lng": 30.52, "radius": 50000, "type": "request"},
        headers=login(client, "volunteer@razom.demo"),
    ).json()
    assert len(items) >= 35
    assert {i["category"] for i in items} == CATEGORIES
    assert all(50.35 <= i["latitude"] <= 50.55 and 30.40 <= i["longitude"] <= 30.70 for i in items)


@pytest.mark.parametrize("email", [e for e in DEMO_ACCOUNTS if e != "blocked@razom.demo"])
def test_every_named_account_logs_in(client, db, email):
    seed_demo(db)
    login(client, email)


def test_resumes_after_partial_seed(db):
    db.add(User(email="volunteer2@razom.demo", password_hash=hash_password(DEMO_PASSWORD),
                display_name="Half-seeded", is_volunteer=True))
    db.commit()
    seed_demo(db)
    assert db.query(User).filter_by(email="resident@razom.demo").one()


def test_seed_is_idempotent(db):
    seed_demo(db)
    seed_demo(db)  # no duplicate-email error


def test_seed_refuses_non_demo_database(client, db):
    make_user(client, "resident")
    with pytest.raises(RuntimeError):
        seed_demo(db)
