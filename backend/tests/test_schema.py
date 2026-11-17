import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import engine


def _columns(table: str) -> set[str]:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            )
        }


def _user(conn) -> int:
    return conn.scalar(
        text(
            "INSERT INTO users (email, password_hash, display_name) "
            "VALUES ('a@b.c', 'x', 'A') RETURNING id"
        )
    )


def test_tables_exist():
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables"))}
    assert {"claim_history", "address_access_log"} <= names


def test_new_columns():
    assert {"accepted_at", "closed_at", "is_hidden"} <= _columns("help_requests")
    assert {"category", "is_hidden"} <= _columns("opportunities")


def test_phone_dropped():
    assert "phone" not in _columns("users")


def test_accept_requires_claimer():
    with pytest.raises(IntegrityError), engine.begin() as conn:
        uid = _user(conn)
        conn.execute(
            text(
                "INSERT INTO help_requests (author_id, category, description, location, accepted_at) "
                "VALUES (:u, 'water', 'd', 'SRID=4326;POINT(30 50)', now())"
            ),
            {"u": uid},
        )


def test_completed_requires_claimer():
    with pytest.raises(IntegrityError), engine.begin() as conn:
        uid = _user(conn)
        conn.execute(
            text(
                "INSERT INTO help_requests (author_id, category, description, location, status) "
                "VALUES (:u, 'water', 'd', 'SRID=4326;POINT(30 50)', 'completed')"
            ),
            {"u": uid},
        )


def test_opportunity_category_check():
    with pytest.raises(IntegrityError), engine.begin() as conn:
        uid = _user(conn)
        org = conn.scalar(
            text("INSERT INTO organizations (user_id, org_name) VALUES (:u, 'O') RETURNING id"),
            {"u": uid},
        )
        conn.execute(
            text(
                "INSERT INTO opportunities (organization_id, title, location, start_time, slots_total, category) "
                "VALUES (:o, 't', 'SRID=4326;POINT(30 50)', now(), 1, 'weapons')"
            ),
            {"o": org},
        )
