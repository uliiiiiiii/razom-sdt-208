import pytest

from app.demo_seed import DEMO_ACCOUNTS, DEMO_PASSWORD, seed_demo
from conftest import make_user


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, email
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_seed_creates_one_account_per_role_and_content(client, db):
    seed_demo(db)
    roles = {
        email: client.get("/api/auth/me", headers=login(client, email)).json()["roles"]
        for email in DEMO_ACCOUNTS
    }
    assert roles["resident@razom.demo"] == ["resident"]
    assert roles["volunteer@razom.demo"] == ["volunteer"]
    assert roles["moderator@razom.demo"] == ["moderator"]
    vol = login(client, "volunteer@razom.demo")
    items = client.get("/api/map", params={"lat": 50.45, "lng": 30.52, "radius": 10000}, headers=vol).json()
    assert sorted(i["type"] for i in items) == ["opportunity", "opportunity", "request", "request"]
    pending = client.get("/api/me/organization", headers=login(client, "pending-org@razom.demo")).json()
    assert pending["verification_status"] == "pending"


def test_seed_is_idempotent(db):
    seed_demo(db)
    seed_demo(db)  # no duplicate-email error


def test_seed_refuses_non_demo_database(client, db):
    make_user(client, "resident")
    with pytest.raises(RuntimeError):
        seed_demo(db)
