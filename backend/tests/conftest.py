"""Shared test setup: a real PostGIS database `razom_test`, migrated with Alembic.

Env vars must be set before `app` is imported, because settings are read at import.
"""
import os

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+psycopg2://razom:razom@localhost:5433/razom_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 52
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


_ensure_database(os.environ["DATABASE_URL"])

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import upgrade_to_head  # noqa: E402

upgrade_to_head(os.environ["DATABASE_URL"])

KEEP_TABLES = {"spatial_ref_sys", "alembic_version"}


@pytest.fixture(autouse=True)
def _clean_tables():
    with engine.begin() as conn:
        tables = [
            r[0]
            for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
            if r[0] not in KEEP_TABLES
        ]
        if tables:
            conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


_counter = {"n": 0}


def make_user(client, *roles: str, org_name: str | None = None) -> dict:
    """Register + log in a user with the given self-selectable roles."""
    _counter["n"] += 1
    email = f"user{_counter['n']}@test.com"
    body = {"email": email, "password": "secret12", "display_name": f"User {_counter['n']}"}
    body.update({f"is_{r}": True for r in roles})
    if org_name:
        body["org_name"] = org_name
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 201, r.text
    return _login(client, email, r.json()["id"])


def make_moderator(client) -> dict:
    user = make_user(client, "volunteer")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET is_moderator = true, is_volunteer = false WHERE id = :i"),
            {"i": user["id"]},
        )
    return user


def make_org(client, approved: bool = True) -> dict:
    """Organization user; adds "org_id". Approval is set directly in the DB."""
    user = make_user(client, "organization", org_name=f"Shelter {_counter['n'] + 1}")
    with engine.begin() as conn:
        user["org_id"] = conn.scalar(
            text("SELECT id FROM organizations WHERE user_id = :u"), {"u": user["id"]}
        )
        if approved:
            conn.execute(
                text("UPDATE organizations SET verification_status = 'approved' WHERE id = :o"),
                {"o": user["org_id"]},
            )
    return user


def new_opportunity(client, org: dict, **overrides):
    from datetime import datetime, timedelta, timezone

    body = {
        "title": "Dog walking",
        "category": "pets",
        "description": "Walk shelter dogs",
        "latitude": 50.46,
        "longitude": 30.51,
        "start_time": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "slots_total": 2,
    } | overrides
    return client.post("/api/opportunities", json=body, headers=org["h"])


def _login(client, email: str, user_id: int) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": "secret12"})
    assert r.status_code == 200, r.text
    return {"id": user_id, "email": email, "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}


def claim_ref(client, user: dict, rid: int) -> dict:
    """Body for accept/decline: the claim the user (the author) currently sees."""
    claimer = client.get(f"/api/requests/{rid}", headers=user["h"]).json().get("claimer")
    return {"claim_id": claimer["claim_id"] if claimer else 0}


def new_request(client, user: dict, **overrides):
    body = {
        "category": "water",
        "description": "Need water",
        "latitude": 50.4501,
        "longitude": 30.5234,
        "address": "Khreshchatyk 1, apt 5",
    } | overrides
    return client.post("/api/requests", json=body, headers=user["h"])
