"""Reports, auto-hide and moderation (FR 5, 16, 24-27)."""
import pytest
from sqlalchemy import text

from app.database import engine
from conftest import make_moderator, make_org, make_user, new_opportunity, new_request

CENTER = {"lat": 50.45, "lng": 30.52}


def report(client, user, target_type, target_id, reason="Looks like a scam"):
    return client.post(
        "/api/reports",
        json={"target_type": target_type, "target_id": target_id, "reason": reason},
        headers=user["h"],
    )


def on_map(client, user, kind="all"):
    items = client.get("/api/map", params=CENTER | {"type": kind}, headers=user["h"]).json()
    return {(i["type"], i["id"]) for i in items}


def three_reports(client, target_type, target_id):
    for _ in range(3):
        assert report(client, make_user(client, "volunteer"), target_type, target_id).status_code == 201


def decide(client, mod, report_id, decision):
    return client.patch(
        f"/api/moderation/reports/{report_id}", json={"decision": decision}, headers=mod["h"]
    )


def test_report_and_duplicate(client):
    rid = new_request(client, make_user(client, "resident")).json()["id"]
    vol = make_user(client, "volunteer")
    r = report(client, vol, "request", rid)
    assert r.status_code == 201 and r.json()["status"] == "open"
    assert report(client, vol, "request", rid).status_code == 409


def test_report_validation(client):
    vol = make_user(client, "volunteer")
    assert report(client, vol, "request", 999).status_code == 404
    assert report(client, vol, "planet", 1).status_code == 422
    assert report(client, vol, "user", vol["id"], reason="x").status_code == 422


def test_cannot_report_self(client):
    res = make_user(client, "resident")
    rid = new_request(client, res).json()["id"]
    assert report(client, res, "request", rid).status_code == 400
    assert report(client, res, "user", res["id"]).status_code == 400


def test_auto_hide_after_3(client):
    res = make_user(client, "resident")
    rid = new_request(client, res).json()["id"]
    vol = make_user(client, "volunteer")
    report(client, vol, "request", rid)
    report(client, make_user(client, "volunteer"), "request", rid)
    assert ("request", rid) in on_map(client, vol)
    report(client, make_user(client, "volunteer"), "request", rid)
    assert ("request", rid) not in on_map(client, vol)
    assert client.get(f"/api/requests/{rid}", headers=res["h"]).status_code == 200
    assert client.get(f"/api/requests/{rid}", headers=vol["h"]).status_code == 404


def test_auto_hide_opportunity_after_3(client):
    oid = new_opportunity(client, make_org(client)).json()["id"]
    three_reports(client, "opportunity", oid)
    assert ("opportunity", oid) not in on_map(client, make_user(client, "volunteer"))


def test_auto_suspend_user_after_3(client):
    bad = make_user(client, "volunteer")
    three_reports(client, "user", bad["id"])
    assert client.get("/api/auth/me", headers=bad["h"]).status_code == 401


def test_report_list_counts(client):
    mod = make_moderator(client)
    rid = new_request(client, make_user(client, "resident")).json()["id"]
    report(client, make_user(client, "volunteer"), "request", rid)
    report(client, make_user(client, "volunteer"), "request", rid)
    rows = client.get("/api/moderation/reports", params={"status": "open"}, headers=mod["h"]).json()
    assert len(rows) == 2
    assert {r["open_reports_on_target"] for r in rows} == {2}
    assert rows[0]["reporter"]["display_name"].startswith("User")


def test_moderator_sees_address_only_with_open_report(client):
    mod = make_moderator(client)
    rid = new_request(client, make_user(client, "resident")).json()["id"]
    rep = report(client, make_user(client, "volunteer"), "request", rid).json()
    detail = client.get(f"/api/moderation/reports/{rep['id']}", headers=mod["h"]).json()
    assert detail["target"]["address"] == "Khreshchatyk 1, apt 5"
    with engine.connect() as conn:
        log = conn.execute(
            text("SELECT user_id, via FROM address_access_log WHERE request_id = :r"), {"r": rid}
        ).all()
    assert log == [(mod["id"], "report_review")]
    assert decide(client, mod, rep["id"], "dismiss").status_code == 200
    detail = client.get(f"/api/moderation/reports/{rep['id']}", headers=mod["h"]).json()
    assert detail["target"]["address"] is None and detail["status"] == "dismissed"
    # the regular endpoint never reveals it to a moderator
    assert client.get(f"/api/requests/{rid}", headers=mod["h"]).json()["address"] is None


def test_dismiss_restores_and_resolves_all(client):
    mod = make_moderator(client)
    rid = new_request(client, make_user(client, "resident")).json()["id"]
    three_reports(client, "request", rid)
    rows = client.get("/api/moderation/reports", headers=mod["h"]).json()
    assert decide(client, mod, rows[0]["id"], "dismiss").status_code == 200
    assert ("request", rid) in on_map(client, make_user(client, "volunteer"))
    assert client.get("/api/moderation/reports", headers=mod["h"]).json() == []
    assert decide(client, mod, rows[1]["id"], "hide").status_code == 409  # already resolved


def test_hide_decision(client):
    mod = make_moderator(client)
    oid = new_opportunity(client, make_org(client)).json()["id"]
    rep = report(client, make_user(client, "volunteer"), "opportunity", oid).json()
    assert decide(client, mod, rep["id"], "hide").json()["status"] == "actioned"
    assert ("opportunity", oid) not in on_map(client, make_user(client, "volunteer"))


def test_hide_user_target_rejected(client):
    mod = make_moderator(client)
    bad = make_user(client, "volunteer")
    rep = report(client, make_user(client, "volunteer"), "user", bad["id"]).json()
    assert decide(client, mod, rep["id"], "hide").status_code == 400


def test_block_from_content_report(client):
    mod = make_moderator(client)
    res = make_user(client, "resident")
    rid = new_request(client, res).json()["id"]
    rep = report(client, make_user(client, "volunteer"), "request", rid).json()
    assert decide(client, mod, rep["id"], "block").status_code == 200
    assert client.get("/api/auth/me", headers=res["h"]).status_code == 401


def test_org_verification_flow(client):
    mod = make_moderator(client)
    good, bad = make_org(client, approved=False), make_org(client, approved=False)
    pending = client.get(
        "/api/moderation/organizations", params={"status": "pending"}, headers=mod["h"]
    ).json()
    assert {o["id"] for o in pending} == {good["org_id"], bad["org_id"]}
    r = client.patch(
        f"/api/moderation/organizations/{good['org_id']}",
        json={"decision": "approved", "comment": "Checked the registry"},
        headers=mod["h"],
    )
    assert r.status_code == 200 and r.json()["verification_status"] == "approved"
    assert new_opportunity(client, good).status_code == 201
    client.patch(
        f"/api/moderation/organizations/{bad['org_id']}",
        json={"decision": "rejected", "comment": "Documents missing"},
        headers=mod["h"],
    )
    me = client.get("/api/me/organization", headers=bad["h"]).json()
    assert me == {
        "id": bad["org_id"], "org_name": me["org_name"],
        "verification_status": "rejected", "comment": "Documents missing",
    }
    assert new_opportunity(client, bad).status_code == 403


def test_promote_without_relogin(client):
    mod = make_moderator(client)
    vol = make_user(client, "volunteer")
    assert client.get("/api/moderation/reports", headers=vol["h"]).status_code == 403
    r = client.patch(f"/api/moderation/users/{vol['id']}", json={"is_moderator": True}, headers=mod["h"])
    assert r.status_code == 200 and "moderator" in r.json()["roles"]
    assert client.get("/api/moderation/reports", headers=vol["h"]).status_code == 200
    client.patch(f"/api/moderation/users/{vol['id']}", json={"is_blocked": True}, headers=mod["h"])
    assert client.get("/api/moderation/reports", headers=vol["h"]).status_code == 401


def test_user_search(client):
    mod = make_moderator(client)
    vol = make_user(client, "volunteer")
    rows = client.get("/api/moderation/users", params={"q": vol["email"][:6]}, headers=mod["h"]).json()
    assert vol["id"] in [u["id"] for u in rows]


def test_cannot_change_self(client):
    mod = make_moderator(client)
    r = client.patch(f"/api/moderation/users/{mod['id']}", json={"is_moderator": False}, headers=mod["h"])
    assert r.status_code == 400


def test_access_log_listing(client):
    mod = make_moderator(client)
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    client.patch(f"/api/requests/{rid}/claim", headers=vol["h"])
    client.patch(f"/api/requests/{rid}/accept", headers=res["h"])
    client.get(f"/api/requests/{rid}", headers=vol["h"])
    rows = client.get("/api/moderation/access-log", params={"request_id": rid}, headers=mod["h"]).json()
    assert rows and all(r["user"]["id"] == vol["id"] and r["via"] == "claim" for r in rows)


MODERATION_ROUTES = [
    ("get", "/api/moderation/reports"),
    ("get", "/api/moderation/reports/1"),
    ("patch", "/api/moderation/reports/1"),
    ("get", "/api/moderation/organizations"),
    ("patch", "/api/moderation/organizations/1"),
    ("get", "/api/moderation/users"),
    ("patch", "/api/moderation/users/1"),
    ("get", "/api/moderation/access-log"),
]


@pytest.mark.parametrize("method,url", MODERATION_ROUTES)
def test_non_moderator_403(client, method, url):
    vol = make_user(client, "volunteer")
    r = getattr(client, method)(url, headers=vol["h"], **({"json": {}} if method == "patch" else {}))
    assert r.status_code == 403
