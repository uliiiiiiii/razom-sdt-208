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


def _verification(conn, uid: int, status: str) -> int:
    return conn.scalar(
        text(
            "INSERT INTO identity_verifications (user_id, status, challenge_word, "
            "challenge_expires_at) VALUES (:u, :s, 'river-lamp', now()) RETURNING id"
        ),
        {"u": uid, "s": status},
    )


def test_verification_tables_exist():
    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables"))}
        assert {"identity_verifications", "verification_images", "verification_access_log"} <= names
        assert {"is_verified", "verified_at", "photo_image_id", "only_verified_residents"} <= _columns("users")
        assert "verified_only" in _columns("help_requests")
        uid = _user(conn)
        row = conn.execute(
            text("SELECT is_verified, only_verified_residents FROM users WHERE id = :u"), {"u": uid}
        ).one()
        assert row == (False, False)
        conn.rollback()


def test_verification_status_check():
    with pytest.raises(IntegrityError), engine.begin() as conn:
        _verification(conn, _user(conn), "bogus")


def test_one_open_verification_per_user():
    with pytest.raises(IntegrityError), engine.begin() as conn:
        uid = _user(conn)
        _verification(conn, uid, "pending")
        _verification(conn, uid, "pending")
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
        uid = _user(conn)
        _verification(conn, uid, "pending")
        _verification(conn, uid, "rejected")


def test_deleting_image_clears_user_photo():
    with engine.begin() as conn:
        uid = _user(conn)
        vid = _verification(conn, uid, "pending")
        img = conn.scalar(
            text(
                "INSERT INTO verification_images (verification_id, kind, data) "
                "VALUES (:v, 'profile', 'x') RETURNING id"
            ),
            {"v": vid},
        )
        conn.execute(text("UPDATE users SET photo_image_id = :i WHERE id = :u"), {"i": img, "u": uid})
        conn.execute(text("DELETE FROM verification_images WHERE id = :i"), {"i": img})
        assert conn.scalar(text("SELECT photo_image_id FROM users WHERE id = :u"), {"u": uid}) is None
