"""Deferred findings from the Beta review: duplicate-email race, report existence
oracle, moderator self-report to read an address."""
from sqlalchemy import text

from app.database import engine
from conftest import make_moderator, make_org, make_user, new_opportunity, new_request


def report(client, user, target_type, target_id):
    return client.post(
        "/api/reports",
        json={"target_type": target_type, "target_id": target_id, "reason": "Looks like a scam"},
        headers=user["h"],
    )


def test_duplicate_email_is_409(client):
    body = {"email": "Dup@Test.com", "password": "secret12", "display_name": "A", "is_resident": True}
    assert client.post("/api/auth/register", json=body).status_code == 201
    r = client.post("/api/auth/register", json=body | {"email": "dup@test.com"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Email already registered"


def test_report_on_request_the_user_cannot_see_is_404(client):
    mod = make_moderator(client)
    rid = new_request(client, make_user(client, "resident")).json()["id"]
    client.patch(f"/api/moderation/requests/{rid}", json={"is_hidden": True}, headers=mod["h"])
    reporter = make_user(client, "volunteer")
    missing = report(client, reporter, "request", 999_999)
    hidden = report(client, reporter, "request", rid)
    assert missing.status_code == hidden.status_code == 404
    assert missing.json() == hidden.json()


def test_report_on_hidden_opportunity_is_404(client):
    mod = make_moderator(client)
    oid = new_opportunity(client, make_org(client)).json()["id"]
    client.patch(f"/api/moderation/opportunities/{oid}", json={"is_hidden": True}, headers=mod["h"])
    assert report(client, make_user(client, "volunteer"), "opportunity", oid).status_code == 404


def test_claimer_can_still_report_their_claimed_request(client):
    rid = new_request(client, make_user(client, "resident")).json()["id"]
    vol = make_user(client, "volunteer")
    assert client.patch(f"/api/requests/{rid}/claim", headers=vol["h"]).status_code == 200
    assert report(client, vol, "request", rid).status_code == 201


def test_moderator_own_report_does_not_reveal_address(client):
    mod = make_moderator(client)
    rid = new_request(client, make_user(client, "resident")).json()["id"]
    own = report(client, mod, "request", rid).json()
    detail = client.get(f"/api/moderation/reports/{own['id']}", headers=mod["h"]).json()
    assert detail["target"]["address"] is None
    with engine.connect() as conn:
        assert conn.scalar(
            text("SELECT count(*) FROM address_access_log WHERE request_id = :r"), {"r": rid}
        ) == 0
    # someone else's report on the same request still lets the moderator review it
    other = report(client, make_user(client, "volunteer"), "request", rid).json()
    detail = client.get(f"/api/moderation/reports/{other['id']}", headers=mod["h"]).json()
    assert detail["target"]["address"] == "Khreshchatyk 1, apt 5"
