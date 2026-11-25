from sqlalchemy import text

from app.database import engine
from tests.conftest import make_moderator, make_user, make_verified, submit_verification

Q = "/api/moderation/verifications"


def _sql(q, **p):
    with engine.begin() as c:
        r = c.execute(text(q), p)
        return r.fetchall() if r.returns_rows else None


def _vid(client, mod, user):
    rows = client.get(Q, headers=mod["h"]).json()
    return next(x["id"] for x in rows if x["user"]["id"] == user["id"])


def _decide(client, mod, vid, decision, comment=None):
    body = {"decision": decision} | ({"comment": comment} if comment is not None else {})
    return client.patch(f"{Q}/{vid}", headers=mod["h"], json=body)


def test_queue_oldest_first_excludes_own_and_blocked(client):
    mod = make_moderator(client)
    a, b, c = (make_user(client, "resident") for _ in range(3))
    both = make_user(client, "volunteer")
    _sql("UPDATE users SET is_moderator = true WHERE id = :i", i=both["id"])
    submit_verification(client, a)
    submit_verification(client, both)
    submit_verification(client, b)
    submit_verification(client, c, "ZZ999999")
    _sql("UPDATE users SET is_blocked = true WHERE id = :i", i=b["id"])
    rows = client.get(Q, headers=mod["h"]).json()
    assert [r["user"]["id"] for r in rows] == [a["id"], both["id"], c["id"]]
    assert rows[0]["duplicates"] == [] and "roles" in rows[0]["user"]
    # the moderator-with-a-role does not see their own entry
    rows = client.get(Q, headers=both["h"]).json()
    assert both["id"] not in [r["user"]["id"] for r in rows]
    assert client.get(Q, headers=a["h"]).status_code == 403


def test_view_image_decrypts_and_logs_each_view(client):
    mod, u = make_moderator(client), make_user(client, "resident")
    submit_verification(client, u)
    vid = _vid(client, mod, u)
    assert client.get(f"{Q}/{vid}", headers=mod["h"]).json()["images"]
    for _ in range(2):
        r = client.get(f"{Q}/{vid}/images/selfie", headers=mod["h"])
        assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "private, no-store"
    assert _sql("SELECT count(*) FROM verification_access_log")[0][0] == 2
    log = client.get(f"/api/moderation/verification-access-log?verification_id={vid}", headers=mod["h"]).json()
    assert len(log) == 2 and log[0]["kind"] == "selfie" and log[0]["moderator"]["id"] == mod["id"]
    assert client.get(f"{Q}/{vid}/images/passport", headers=mod["h"]).status_code == 422


def test_own_submission_is_403(client):
    mod = make_moderator(client)
    submit_verification(client, mod)
    vid = _sql("SELECT id FROM identity_verifications")[0][0]
    assert client.get(f"{Q}/{vid}", headers=mod["h"]).status_code == 403
    assert client.get(f"{Q}/{vid}/images/selfie", headers=mod["h"]).status_code == 403
    assert _decide(client, mod, vid, "approved").status_code == 403


def test_approve(client):
    mod, u = make_moderator(client), make_user(client, "resident")
    submit_verification(client, u)
    vid = _vid(client, mod, u)
    assert _decide(client, mod, vid, "approved").status_code == 200
    me = _sql("SELECT is_verified, photo_image_id FROM users WHERE id = :i", i=u["id"])[0]
    prof = _sql("SELECT id FROM verification_images WHERE kind = 'profile'")
    assert me[0] is True and [me[1]] == [prof[0][0]]
    assert _sql("SELECT count(*) FROM verification_images WHERE kind <> 'profile'")[0][0] == 0
    assert client.get(f"{Q}/{vid}/images/profile", headers=mod["h"]).status_code == 404
    assert _decide(client, mod, vid, "approved").status_code == 409


def test_reject_needs_comment_and_deletes_everything(client):
    mod, u = make_moderator(client), make_user(client, "resident")
    submit_verification(client, u)
    vid = _vid(client, mod, u)
    assert _decide(client, mod, vid, "rejected").status_code == 422
    assert _decide(client, mod, vid, "rejected", "   ").status_code == 422
    assert _decide(client, mod, vid, "rejected", "x" * 501).status_code == 422
    assert _decide(client, mod, vid, "rejected", "Blurry").status_code == 200
    assert _sql("SELECT count(*) FROM verification_images")[0][0] == 0
    me = client.get("/api/me/verification", headers=u["h"]).json()
    assert me["status"] == "rejected" and me["comment"] == "Blurry"
    assert client.post("/api/me/verification/start", headers=u["h"]).status_code == 200


def test_reapproval_keeps_one_profile_photo(client):
    mod, u = make_moderator(client), make_user(client, "resident")
    make_verified(client, u, mod)
    _sql("UPDATE users SET is_verified = false WHERE id = :i", i=u["id"])
    make_verified(client, u, mod)
    rows = _sql("SELECT id FROM verification_images WHERE kind = 'profile'")
    assert len(rows) == 1
    assert _sql("SELECT photo_image_id FROM users WHERE id = :i", i=u["id"])[0][0] == rows[0][0]


def test_duplicate_fingerprint_warns(client):
    mod = make_moderator(client)
    a, b = make_user(client, "resident"), make_user(client, "resident")
    submit_verification(client, a, "AB123456")
    make_verified_a = _vid(client, mod, a)
    assert _decide(client, mod, make_verified_a, "approved").status_code == 200
    submit_verification(client, b, "АВ 123-456")
    row = next(r for r in client.get(Q, headers=mod["h"]).json() if r["user"]["id"] == b["id"])
    assert [d["id"] for d in row["duplicates"]] == [a["id"]]


def test_approve_blocked_user_is_409(client):
    mod, u = make_moderator(client), make_user(client, "resident")
    submit_verification(client, u)
    vid = _vid(client, mod, u)
    _sql("UPDATE users SET is_blocked = true WHERE id = :i", i=u["id"])
    assert _decide(client, mod, vid, "approved").status_code == 409
