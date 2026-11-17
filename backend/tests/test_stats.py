"""Organization and platform statistics (FR 28-29)."""
from sqlalchemy import text

from app.database import engine
from conftest import make_moderator, make_org, make_user, new_opportunity, new_request

EXPECTED_ORG = {
    "opportunities_total": 2,
    "opportunities_open": 2,
    "signups_total": 3,
    "attended_total": 1,
    "past_opportunities": 1,
}


def org_with_activity(client) -> dict:
    org = make_org(client)
    o1 = new_opportunity(client, org).json()["id"]
    o2 = new_opportunity(client, org).json()["id"]
    vols = [make_user(client, "volunteer") for _ in range(2)]
    sids = [client.post(f"/api/opportunities/{o1}/signups", headers=v["h"]).json()["id"] for v in vols]
    client.post(f"/api/opportunities/{o2}/signups", headers=vols[0]["h"])
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE opportunities SET start_time = now() - interval '1 hour' WHERE id = :o"),
            {"o": o1},
        )
    client.patch(f"/api/opportunities/{o1}/signups/{sids[0]}", json={"attended": True}, headers=org["h"])
    return org


def test_org_stats_counts(client):
    org = org_with_activity(client)
    r = client.get("/api/me/organization/stats", headers=org["h"])
    assert r.status_code == 200 and r.json() == EXPECTED_ORG


def test_moderator_sees_any_org_stats(client):
    org = org_with_activity(client)
    mod = make_moderator(client)
    r = client.get(f"/api/moderation/organizations/{org['org_id']}/stats", headers=mod["h"])
    assert r.json() == EXPECTED_ORG
    assert client.get("/api/moderation/organizations/999/stats", headers=mod["h"]).status_code == 404


def test_platform_stats(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res, category="water").json()["id"]
    new_request(client, res, category="medicine")
    client.patch(f"/api/requests/{rid}/claim", headers=vol["h"])
    reporter = make_user(client, "volunteer")
    client.post(
        "/api/reports",
        json={"target_type": "user", "target_id": res["id"], "reason": "spam spam"},
        headers=reporter["h"],
    )
    make_org(client, approved=False)
    mod = make_moderator(client)
    r = client.get("/api/moderation/stats", headers=mod["h"])
    assert r.status_code == 200
    assert r.json() == {
        "requests_by_status": {"open": 1, "claimed": 1},
        "requests_by_category": {"water": 1, "medicine": 1},
        "users_total": 5,
        "active_users_30d": 2,
        "pending_reports": 1,
        "pending_organizations": 1,
    }


def test_stats_forbidden_for_other_roles(client):
    vol = make_user(client, "volunteer")
    assert client.get("/api/me/organization/stats", headers=vol["h"]).status_code == 403
    assert client.get("/api/moderation/stats", headers=vol["h"]).status_code == 403
    assert client.get("/api/moderation/organizations/1/stats", headers=vol["h"]).status_code == 403
