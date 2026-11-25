import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.database import engine
from tests.conftest import make_user, png_bytes, submit_verification

URL = "/api/me/verification"


def _files(**over):
    f = {k: (f"{k}.png", png_bytes(), "image/png") for k in ("id_document", "selfie", "profile")}
    f.update({k: (k, v, "image/png") for k, v in over.items()})
    return f


def _submit(client, u, number="AB123456", **over):
    return client.post(URL, headers=u["h"], files=_files(**over), data={"document_number": number})


def _sql(q, **p):
    with engine.begin() as c:
        r = c.execute(text(q), p)
        return r.fetchall() if r.returns_rows else None


def test_start_gives_two_word_challenge(client):
    u = make_user(client, "resident")
    r = client.post(URL + "/start", headers=u["h"])
    assert r.status_code == 200
    assert re.fullmatch(r"[a-z]+-[a-z]+", r.json()["word"])
    exp = datetime.fromisoformat(r.json()["expires_at"])
    assert abs(exp - (datetime.now(timezone.utc) + timedelta(hours=24))) < timedelta(minutes=1)
    assert client.post(URL + "/start", headers=u["h"]).status_code == 200
    assert _sql("SELECT status FROM identity_verifications") == [("started",)]


def test_submit_without_or_after_expired_start_is_409(client):
    u = make_user(client, "resident")
    assert _submit(client, u).status_code == 409
    client.post(URL + "/start", headers=u["h"])
    _sql("UPDATE identity_verifications SET challenge_expires_at = now() - interval '1 minute'")
    assert _submit(client, u).status_code == 409


def test_submit_stores_encrypted_images_and_fingerprint_only(client):
    u = make_user(client, "resident")
    assert submit_verification(client, u)["status"] == "pending"
    imgs = _sql("SELECT data FROM verification_images")
    assert len(imgs) == 3
    assert not any(bytes(d).startswith(b"\xff\xd8") for (d,) in imgs)
    fp = _sql("SELECT document_fingerprint FROM identity_verifications")[0][0]
    assert re.fullmatch(r"[0-9a-f]{64}", fp)
    row = _sql("SELECT identity_verifications::text FROM identity_verifications")[0][0]
    assert "AB123456" not in row


def test_start_while_pending_or_verified_is_409(client):
    u = make_user(client, "resident")
    submit_verification(client, u)
    assert client.post(URL + "/start", headers=u["h"]).status_code == 409
    _sql("UPDATE identity_verifications SET status='approved'")
    _sql("UPDATE users SET is_verified = true")
    assert client.post(URL + "/start", headers=u["h"]).status_code == 409


def test_bad_image_leaves_challenge_intact(client):
    u = make_user(client, "resident")
    client.post(URL + "/start", headers=u["h"])
    assert _submit(client, u, selfie=b"junk").status_code == 422
    assert client.get(URL, headers=u["h"]).json()["status"] == "started"
    assert _sql("SELECT 1 FROM verification_images") == []


def test_double_submit_one_pending_one_409(client):
    u = make_user(client, "resident")
    client.post(URL + "/start", headers=u["h"])
    codes = sorted(_submit(client, u).status_code for _ in range(2))
    assert codes == [200, 409]


def test_document_number_of_separators_is_422(client):
    u = make_user(client, "resident")
    client.post(URL + "/start", headers=u["h"])
    assert _submit(client, u, number=" - - ").status_code == 422


def test_my_verification_shapes(client):
    u = make_user(client, "resident")
    assert client.get(URL, headers=u["h"]).json()["status"] == "none"
    client.post(URL + "/start", headers=u["h"])
    j = client.get(URL, headers=u["h"]).json()
    assert j["status"] == "started" and j["word"] and j["expires_at"]
    submit_verification(client, u)
    j = client.get(URL, headers=u["h"]).json()
    assert j["status"] == "pending" and j["word"] is None and j["submitted_at"]


def test_settings_toggle(client):
    u = make_user(client, "resident")
    r = client.patch("/api/me/settings", json={"only_verified_residents": True}, headers=u["h"])
    assert r.status_code == 200 and r.json() == {"only_verified_residents": True}


def test_whitespace_only_document_number_is_422(client):
    u = make_user(client, "resident")
    client.post(URL + "/start", headers=u["h"])
    assert _submit(client, u, "				").status_code == 422
