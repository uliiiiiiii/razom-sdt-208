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


def _login(client, email: str, user_id: int) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": "secret12"})
    assert r.status_code == 200, r.text
    return {"id": user_id, "email": email, "h": {"Authorization": f"Bearer {r.json()['access_token']}"}}


def new_request(client, user: dict, **overrides):
    body = {
        "category": "water",
        "description": "Need water",
        "latitude": 50.4501,
        "longitude": 30.5234,
        "address": "Khreshchatyk 1, apt 5",
    } | overrides
    return client.post("/api/requests", json=body, headers=user["h"])
