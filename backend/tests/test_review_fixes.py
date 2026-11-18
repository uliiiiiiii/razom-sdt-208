"""Regression tests for the Beta whole-branch review findings (C1, I1-I8, minors)."""
import math

import jwt
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.geo import round_location
from conftest import make_moderator, make_org, make_user, new_opportunity, new_request

CENTER = {"lat": 50.45, "lng": 30.52}


def act(client, user, rid, action, body=None):
    return client.patch(f"/api/requests/{rid}/{action}", headers=user["h"], json=body)


def sql(stmt, **params):
    with engine.begin() as conn:
        return conn.execute(text(stmt), params)


def claim_id_seen_by(client, res, rid):
    return client.get(f"/api/requests/{rid}", headers=res["h"]).json()["claimer"]["claim_id"]


def report(client, user, target_type, target_id):
    return client.post(
        "/api/reports",
        json={"target_type": target_type, "target_id": target_id, "reason": "bad actor"},
        headers=user["h"],
    )


def three_reports(client, target_type, target_id):
    for _ in range(3):
        report(client, make_user(client, "volunteer"), target_type, target_id)


def on_map(client, user):
    return {(i["type"], i["id"]) for i in client.get("/api/map", params=CENTER, headers=user["h"]).json()}


# --- C1: accept is bound to the volunteer the resident saw -------------------
def test_accept_requires_claim_id(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    assert act(client, res, rid, "accept").status_code == 422
    cid = claim_id_seen_by(client, res, rid)
    assert act(client, res, rid, "accept", {"claim_id": cid}).status_code == 200


def test_stale_accept_rejected(client):
    res = make_user(client, "resident")
    a, b = make_user(client, "volunteer"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, a, rid, "claim")
    seen = claim_id_seen_by(client, res, rid)  # resident looks at volunteer A
    act(client, a, rid, "release")
    act(client, b, rid, "claim")  # B takes over before the resident clicks
    r = act(client, res, rid, "accept", {"claim_id": seen})
    assert r.status_code == 409
    assert client.get(f"/api/requests/{rid}", headers=b["h"]).json()["address"] is None


def test_stale_decline_rejected(client):
    res = make_user(client, "resident")
    a, b = make_user(client, "volunteer"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, a, rid, "claim")
    seen = claim_id_seen_by(client, res, rid)
    act(client, a, rid, "release")
    act(client, b, rid, "claim")
    assert act(client, res, rid, "decline", {"claim_id": seen}).status_code == 409


def test_ex_claimer_after_decline(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    act(client, res, rid, "decline", {"claim_id": claim_id_seen_by(client, res, rid)})
    d = client.get(f"/api/requests/{rid}", headers=vol["h"]).json()
    assert d["address"] is None and d["is_claimer"] is False


# --- I1: unaccepted claims expire; blocking releases claims ------------------
def test_unaccepted_claim_expires(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    assert ("request", rid) not in on_map(client, vol)
    sql("UPDATE help_requests SET claimed_at = now() - interval '13 hours' WHERE id = :r", r=rid)
    assert ("request", rid) in on_map(client, vol)
    outcome = sql("SELECT outcome FROM claim_history WHERE request_id = :r", r=rid).scalar()
    assert outcome == "released"


def test_accepted_claim_does_not_expire(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    act(client, res, rid, "accept", {"claim_id": claim_id_seen_by(client, res, rid)})
    sql("UPDATE help_requests SET claimed_at = now() - interval '2 days' WHERE id = :r", r=rid)
    on_map(client, vol)
    assert client.get(f"/api/requests/{rid}", headers=res["h"]).json()["status"] == "claimed"


def test_blocking_volunteer_releases_claims(client):
    mod = make_moderator(client)
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    client.patch(f"/api/moderation/users/{vol['id']}", json={"is_blocked": True}, headers=mod["h"])
    assert client.get(f"/api/requests/{rid}", headers=res["h"]).json()["status"] == "open"


# --- I2: moderators are never auto-suspended ---------------------------------
def test_moderator_not_auto_suspended(client):
    mod = make_moderator(client)
    three_reports(client, "user", mod["id"])
    assert client.get("/api/auth/me", headers=mod["h"]).status_code == 200


# --- I3: dismiss restores only automatic hides; manual unhide; owner sees it -
def test_dismiss_does_not_undo_manual_block(client):
    mod = make_moderator(client)
    bad = make_user(client, "volunteer")
    client.patch(f"/api/moderation/users/{bad['id']}", json={"is_blocked": True}, headers=mod["h"])
    rep = report(client, make_user(client, "volunteer"), "user", bad["id"]).json()
    client.patch(f"/api/moderation/reports/{rep['id']}", json={"decision": "dismiss"}, headers=mod["h"])
    assert sql("SELECT is_blocked FROM users WHERE id = :u", u=bad["id"]).scalar() is True


def test_dismiss_restores_auto_block(client):
    mod = make_moderator(client)
    bad = make_user(client, "volunteer")
    three_reports(client, "user", bad["id"])
    rid = client.get("/api/moderation/reports", headers=mod["h"]).json()[0]["id"]
    client.patch(f"/api/moderation/reports/{rid}", json={"decision": "dismiss"}, headers=mod["h"])
    assert client.get("/api/auth/me", headers=bad["h"]).status_code == 200


def test_moderator_can_unhide_content(client):
    mod = make_moderator(client)
    res = make_user(client, "resident")
    rid = new_request(client, res).json()["id"]
    oid = new_opportunity(client, make_org(client)).json()["id"]
    for kind, i in (("requests", rid), ("opportunities", oid)):
        r = client.patch(f"/api/moderation/{kind}/{i}", json={"is_hidden": True}, headers=mod["h"])
        assert r.status_code == 200
    vol = make_user(client, "volunteer")
    assert on_map(client, vol) == set()
    assert client.get(f"/api/requests/{rid}", headers=res["h"]).json()["is_hidden"] is True
    for kind, i in (("requests", rid), ("opportunities", oid)):
        client.patch(f"/api/moderation/{kind}/{i}", json={"is_hidden": False}, headers=mod["h"])
    assert on_map(client, vol) == {("request", rid), ("opportunity", oid)}


def test_owner_sees_hidden_opportunity_flag(client):
    org = make_org(client)
    oid = new_opportunity(client, org).json()["id"]
    sql("UPDATE opportunities SET is_hidden = true WHERE id = :o", o=oid)
    assert client.get(f"/api/opportunities/{oid}", headers=org["h"]).json()["is_hidden"] is True


# --- I4: claimer loses exact data once the request is completed --------------
def test_claimer_no_address_after_complete(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    act(client, res, rid, "accept", {"claim_id": claim_id_seen_by(client, res, rid)})
    assert act(client, vol, rid, "complete").json()["address"] is None


# --- I5: Alpha rows get closed_at so retention can purge them ----------------
def test_migration_0003_backfills_closed_at():
    from app.migrate import downgrade_to, upgrade_to_head
    import os

    url = os.environ["DATABASE_URL"]
    downgrade_to(url, "0002")
    with engine.begin() as conn:
        uid = conn.scalar(text("INSERT INTO users (email, password_hash, display_name) VALUES ('m@x.c','x','M') RETURNING id"))
        conn.execute(
            text(
                "INSERT INTO help_requests (author_id, category, description, location, status) "
                "VALUES (:u, 'water', 'd', 'SRID=4326;POINT(30 50)', 'cancelled')"
            ),
            {"u": uid},
        )
    upgrade_to_head(url)
    assert sql("SELECT closed_at IS NOT NULL FROM help_requests").scalar() is True


# --- I6: purge runs periodically, not only at startup ------------------------
def test_purge_is_scheduled():
    from app.main import RETENTION_INTERVAL_SECONDS

    assert RETENTION_INTERVAL_SECONDS == 24 * 3600


# --- I7: blocked / unapproved org content not reachable by link ---------------
def test_blocked_org_opportunity_unreachable(client):
    org = make_org(client)
    oid = new_opportunity(client, org).json()["id"]
    sql("UPDATE users SET is_blocked = true WHERE id = :u", u=org["id"])
    vol = make_user(client, "volunteer")
    assert client.get(f"/api/opportunities/{oid}", headers=vol["h"]).status_code == 404
    assert client.post(f"/api/opportunities/{oid}/signups", headers=vol["h"]).status_code == 404


def test_unapproved_org_opportunity_unreachable(client):
    org = make_org(client)
    oid = new_opportunity(client, org).json()["id"]
    sql("UPDATE organizations SET verification_status = 'rejected' WHERE id = :o", o=org["org_id"])
    vol = make_user(client, "volunteer")
    assert client.get(f"/api/opportunities/{oid}", headers=vol["h"]).status_code == 404
    assert client.get(f"/api/opportunities/{oid}", headers=org["h"]).status_code == 200


def test_cannot_claim_request_of_blocked_author(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    sql("UPDATE users SET is_blocked = true WHERE id = :u", u=res["id"])
    assert act(client, vol, rid, "claim").status_code == 404


# --- I8: API docs usable ------------------------------------------------------
def test_docs_not_blocked_by_csp(client):
    for path in ("/docs", "/openapi.json"):
        r = client.get(path)
        assert r.status_code == 200 and "content-security-policy" not in r.headers


def test_bearer_scheme_in_openapi(client):
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert any(s.get("scheme") == "bearer" for s in schemes.values())


# --- frontend readiness -------------------------------------------------------
def test_csp_allows_osm_tile_host(client):
    csp = client.get("/api/health").headers["content-security-policy"]
    assert "https://tile.openstreetmap.org" in csp


def test_spa_serving(client, tmp_path, monkeypatch):
    import app.main as main

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>razom</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    deep = client.get("/requests/5")
    assert deep.status_code == 200 and "razom" in deep.text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/nope").headers["content-type"].startswith("application/json")
    assert client.get("/../backend/app/config.py").status_code in (200, 404)
    assert "JWT_SECRET" not in client.get("/%2e%2e/backend/app/config.py").text


# --- re-graded minors ---------------------------------------------------------
def test_password_min_8(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "p@x.com", "password": "short7!", "display_name": "P", "is_volunteer": True},
    )
    assert r.status_code == 422


def test_text_length_limits(client):
    res = make_user(client, "resident")
    assert new_request(client, res, description="x" * 2001).status_code == 422
    assert new_request(client, res, address="x" * 301).status_code == 422
    assert new_request(client, res, title="x" * 121).status_code == 422


def test_patch_with_nulls_is_not_500(client):
    org = make_org(client)
    oid = new_opportunity(client, org).json()["id"]
    r = client.patch(f"/api/opportunities/{oid}", json={"title": None, "slots_total": None}, headers=org["h"])
    assert r.status_code == 200 and r.json()["title"] == "Dog walking"


def test_token_without_exp_rejected(client):
    user = make_user(client, "volunteer")
    token = jwt.encode({"sub": str(user["id"])}, settings.jwt_secret, algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_blocked_user_gets_distinct_message(client):
    user = make_user(client, "volunteer")
    sql("UPDATE users SET is_blocked = true WHERE id = :u", u=user["id"])
    r = client.get("/api/auth/me", headers=user["h"])
    assert r.status_code == 401 and r.json()["detail"] == "Account is blocked"


def test_approx_cell_is_about_300m_both_ways():
    lat = 50.45
    base = round_location(lat, 30.5)
    lng, step_lng = 30.5, None
    while step_lng is None:
        lng += 0.0001
        if round_location(lat, lng)[1] != base[1]:
            step_lng = abs(round_location(lat, lng)[1] - base[1])
    metres = step_lng * 111_000 * math.cos(math.radians(lat))
    assert 280 <= metres <= 320
