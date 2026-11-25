"""Losing the badge: revoke, moderator block vs auto-block, stale-submission purge."""
from sqlalchemy import text

from app.database import engine
from tests.conftest import (
    claim_ref,
    make_moderator,
    make_user,
    make_verified,
    new_request,
    submit_verification,
)

MAP = {"lat": 50.45, "lng": 30.52}
Q = "/api/moderation/verifications"


def _sql(q, **p):
    with engine.begin() as c:
        r = c.execute(text(q), p)
        return r.fetchall() if r.returns_rows else None


def _verified(user):
    return _sql("SELECT is_verified FROM users WHERE id = :i", i=user["id"])[0][0]


def _rows(user):
    """[(status, image count)] of the user's verification rows, oldest first."""
    return [
        tuple(r)
        for r in _sql(
            "SELECT v.status, (SELECT count(*) FROM verification_images i WHERE i.verification_id = v.id) "
            "FROM identity_verifications v WHERE v.user_id = :i ORDER BY v.id",
            i=user["id"],
        )
    ]


def _queue_users(client, mod):
    return {x["user"]["id"] for x in client.get(Q, headers=mod["h"]).json()}


def _patch_user(client, mod, user, body):
    return client.patch(f"/api/moderation/users/{user['id']}", headers=mod["h"], json=body)


def _report_user(client, target):
    reporter = make_user(client, "volunteer")
    r = client.post(
        "/api/reports",
        json={"target_type": "user", "target_id": target["id"], "reason": "Looks like a scam"},
        headers=reporter["h"],
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_revoke(client):
    mod = make_moderator(client)
    res, vol, other = (make_user(client, r) for r in ("resident", "volunteer", "volunteer"))
    make_verified(client, vol, mod)
    strict = new_request(client, res, verified_only=True).json()["id"]
    plain = new_request(client, res).json()["id"]
    for rid in (strict, plain):
        assert client.patch(f"/api/requests/{rid}/claim", headers=vol["h"]).status_code == 200
    assert client.get(f"/api/users/{vol['id']}/photo", headers=res["h"]).status_code == 200

    r = _patch_user(
        client, mod, vol, {"is_verified": False, "verification_comment": "Document was forged"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_verified"] is False
    assert client.get("/api/auth/me", headers=vol["h"]).json()["is_verified"] is False
    for viewer in (res, vol, mod):
        assert client.get(f"/api/users/{vol['id']}/photo", headers=viewer["h"]).status_code == 404
    mine = client.get("/api/me/verification", headers=vol["h"]).json()
    assert mine["status"] == "revoked" and mine["comment"] == "Document was forged"
    assert _sql("SELECT count(*) FROM verification_images")[0][0] == 0

    assert client.get(f"/api/requests/{strict}", headers=res["h"]).json()["status"] == "open"
    items = client.get("/api/map", params=MAP, headers=other["h"]).json()
    assert strict in {i["id"] for i in items if i["type"] == "request"}

    seen = client.get(f"/api/requests/{plain}", headers=res["h"]).json()
    assert seen["status"] == "claimed"
    assert seen["claimer"]["is_verified"] is False and seen["claimer"]["photo_url"] is None


def test_cannot_grant_verified_by_patch(client):
    mod, u = make_moderator(client), make_user(client, "volunteer")
    assert _patch_user(client, mod, u, {"is_verified": True}).status_code == 422
    too_long = {"is_verified": False, "verification_comment": "x" * 501}
    assert _patch_user(client, mod, u, too_long).status_code == 422
    assert _verified(u) is False


def test_moderator_block_revokes_and_expires_submission(client):
    mod = make_moderator(client)
    vol, pending = make_user(client, "volunteer"), make_user(client, "resident")
    make_verified(client, vol, mod)
    submit_verification(client, pending)

    assert _patch_user(client, mod, vol, {"is_blocked": True}).json()["is_verified"] is False
    assert _rows(vol) == [("revoked", 0)]
    assert _patch_user(client, mod, pending, {"is_blocked": True}).status_code == 200
    assert _rows(pending) == [("expired", 0)]

    r = _patch_user(client, mod, vol, {"is_blocked": False})
    assert r.status_code == 200 and r.json()["is_verified"] is False


def test_block_decision_on_report_revokes(client):
    mod, vol = make_moderator(client), make_user(client, "volunteer")
    make_verified(client, vol, mod)
    report_id = _report_user(client, vol)
    r = client.patch(
        f"/api/moderation/reports/{report_id}", headers=mod["h"], json={"decision": "block"}
    )
    assert r.status_code == 200, r.text
    assert _verified(vol) is False
    assert _rows(vol) == [("revoked", 0)]


def test_auto_block_keeps_badge(client):
    mod = make_moderator(client)
    vol, pending = make_user(client, "volunteer"), make_user(client, "resident")
    make_verified(client, vol, mod)
    submit_verification(client, pending)
    vid = next(x["id"] for x in client.get(Q, headers=mod["h"]).json())
    reports = {}
    for target in (vol, pending):
        reports[target["id"]] = [_report_user(client, target) for _ in range(3)][0]
    assert _sql("SELECT bool_and(auto_blocked) FROM users WHERE id IN (:a, :b)",
                a=vol["id"], b=pending["id"])[0][0] is True

    assert _verified(vol) is True
    assert _rows(vol) == [("approved", 1)]  # the profile photo stays
    assert pending["id"] not in _queue_users(client, mod)
    r = client.patch(f"{Q}/{vid}", headers=mod["h"], json={"decision": "approved"})
    assert r.status_code == 409

    for target in (vol, pending):
        r = client.patch(
            f"/api/moderation/reports/{reports[target['id']]}",
            headers=mod["h"],
            json={"decision": "dismiss"},
        )
        assert r.status_code == 200, r.text
    assert _verified(vol) is True
    assert pending["id"] in _queue_users(client, mod)


def test_expire_stale(client, db):
    from app.main import _purge
    from app.verification import expire_stale

    old, started, fresh = (make_user(client, "resident") for _ in range(3))
    submit_verification(client, old)
    submit_verification(client, fresh)
    assert client.post("/api/me/verification/start", headers=started["h"]).status_code == 200
    _sql("UPDATE identity_verifications SET submitted_at = now() - interval '31 days' "
         "WHERE user_id = :i", i=old["id"])
    _sql("UPDATE identity_verifications SET challenge_expires_at = now() - interval '1 minute' "
         "WHERE user_id = :i", i=started["id"])

    assert expire_stale(db) == 2
    assert _rows(old) == [("expired", 0)]
    assert _rows(started) == [("expired", 0)]
    assert _rows(fresh) == [("pending", 3)]

    # the daily purge runs it too
    _sql("UPDATE identity_verifications SET submitted_at = now() - interval '31 days' "
         "WHERE user_id = :i", i=fresh["id"])
    _purge()
    assert _rows(fresh) == [("expired", 0)]


def test_claim_rechecks_verified_at_update_time(client, monkeypatch):
    """A revoke that commits after the claimer was loaded still blocks the claim."""
    import app.routers.requests as requests_router

    mod, res, vol = make_moderator(client), make_user(client, "resident"), make_user(client, "volunteer")
    make_verified(client, vol, mod)
    rid = new_request(client, res, verified_only=True).json()["id"]
    original = requests_router._lock_user

    def revoked_meanwhile(db, user):
        assert user.is_verified  # loaded as verified ...
        _sql("UPDATE users SET is_verified = false WHERE id = :i", i=user.id)  # ... then revoked
        original(db, user)

    monkeypatch.setattr(requests_router, "_lock_user", revoked_meanwhile)
    r = client.patch(f"/api/requests/{rid}/claim", headers=vol["h"])
    assert r.status_code == 403
    assert r.json() == {"detail": "This request is for verified volunteers only"}


def test_blocked_users_photo_is_hidden_except_from_moderators(client):
    mod, res, vol = make_moderator(client), make_user(client, "resident"), make_user(client, "volunteer")
    make_verified(client, vol, mod)
    rid = new_request(client, res).json()["id"]
    client.patch(f"/api/requests/{rid}/claim", headers=vol["h"])
    client.patch(f"/api/requests/{rid}/accept", headers=res["h"], json=claim_ref(client, res, rid))
    assert client.patch(f"/api/requests/{rid}/complete", headers=vol["h"]).status_code == 200
    url = f"/api/users/{vol['id']}/photo"
    assert client.get(url, headers=res["h"]).status_code == 200

    _sql("UPDATE users SET is_blocked = true WHERE id = :i", i=vol["id"])  # as the auto-block does
    r = client.get(url, headers=res["h"])
    assert r.status_code == 404 and r.json() == {"detail": "Photo not found"}
    assert client.get(url, headers=mod["h"]).status_code == 200
