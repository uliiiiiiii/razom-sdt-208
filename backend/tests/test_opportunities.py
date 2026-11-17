"""Organizations, opportunities, sign-ups and attendance (FR 4, 17-20)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import text

from app.database import engine
from conftest import make_org, make_user, new_opportunity


def set_start_in_past(oid: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE opportunities SET start_time = now() - interval '1 hour' WHERE id = :o"),
            {"o": oid},
        )


def signup(client, vol, oid):
    return client.post(f"/api/opportunities/{oid}/signups", headers=vol["h"])


def test_org_register_requires_name(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "o@x.com", "password": "secret12", "display_name": "O", "is_organization": True},
    )
    assert r.status_code == 422


def test_org_register_creates_pending_profile(client):
    org = make_org(client, approved=False)
    r = client.get("/api/me/organization", headers=org["h"])
    assert r.status_code == 200
    assert r.json()["verification_status"] == "pending"


def test_unverified_org_cannot_publish(client):
    org = make_org(client, approved=False)
    r = new_opportunity(client, org)
    assert r.status_code == 403
    assert "verified" in r.json()["detail"]


def test_verified_org_crud(client):
    org = make_org(client)
    r = new_opportunity(client, org)
    assert r.status_code == 201
    opp = r.json()
    assert opp["slots_taken"] == 0 and opp["is_owner"] is True and opp["category"] == "pets"
    r = client.patch(f"/api/opportunities/{opp['id']}", json={"title": "Feeding"}, headers=org["h"])
    assert r.status_code == 200 and r.json()["title"] == "Feeding"
    r = client.patch(f"/api/opportunities/{opp['id']}/close", headers=org["h"])
    assert r.json()["status"] == "closed"
    assert [o["id"] for o in client.get("/api/me/opportunities", headers=org["h"]).json()] == [opp["id"]]


def test_non_owner_cannot_edit(client):
    oid = new_opportunity(client, make_org(client)).json()["id"]
    other = make_org(client)
    assert client.patch(f"/api/opportunities/{oid}", json={"title": "x"}, headers=other["h"]).status_code == 403


def test_signup_slots_and_duplicate(client):
    oid = new_opportunity(client, make_org(client), slots_total=1).json()["id"]
    a, b = make_user(client, "volunteer"), make_user(client, "volunteer")
    assert signup(client, a, oid).status_code == 201
    assert signup(client, a, oid).status_code == 409
    assert signup(client, b, oid).status_code == 409


def test_cancel_frees_slot(client):
    oid = new_opportunity(client, make_org(client), slots_total=1).json()["id"]
    a, b = make_user(client, "volunteer"), make_user(client, "volunteer")
    signup(client, a, oid)
    assert client.delete(f"/api/opportunities/{oid}/signups/me", headers=a["h"]).status_code == 204
    assert signup(client, b, oid).status_code == 201


def test_last_slot_race(client):
    oid = new_opportunity(client, make_org(client), slots_total=1).json()["id"]
    vols = [make_user(client, "volunteer"), make_user(client, "volunteer")]
    with ThreadPoolExecutor(2) as ex:
        codes = sorted(ex.map(lambda v: signup(client, v, oid).status_code, vols))
    assert codes == [201, 409]


def test_slots_cannot_drop_below_taken(client):
    org = make_org(client)
    oid = new_opportunity(client, org, slots_total=2).json()["id"]
    signup(client, make_user(client, "volunteer"), oid)
    signup(client, make_user(client, "volunteer"), oid)
    r = client.patch(f"/api/opportunities/{oid}", json={"slots_total": 1}, headers=org["h"])
    assert r.status_code == 409


def test_signup_after_start_rejected(client):
    oid = new_opportunity(client, make_org(client)).json()["id"]
    set_start_in_past(oid)
    assert signup(client, make_user(client, "volunteer"), oid).status_code == 409


def test_signup_closed_rejected(client):
    org = make_org(client)
    oid = new_opportunity(client, org).json()["id"]
    client.patch(f"/api/opportunities/{oid}/close", headers=org["h"])
    assert signup(client, make_user(client, "volunteer"), oid).status_code == 409


def test_start_time_validation(client):
    org = make_org(client)
    naive = (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat()
    assert new_opportunity(client, org, start_time=naive).status_code == 422
    past = "2020-01-01T10:00:00+00:00"
    assert new_opportunity(client, org, start_time=past).status_code == 422


def test_attendance_only_after_start(client):
    org = make_org(client)
    oid = new_opportunity(client, org).json()["id"]
    vol = make_user(client, "volunteer")
    sid = signup(client, vol, oid).json()["id"]
    url = f"/api/opportunities/{oid}/signups/{sid}"
    assert client.patch(url, json={"attended": True}, headers=org["h"]).status_code == 409
    set_start_in_past(oid)
    assert client.patch(url, json={"attended": True}, headers=org["h"]).status_code == 200
    history = client.get("/api/me/signups", headers=vol["h"]).json()
    assert history[0]["attended"] is True and history[0]["opportunity"]["id"] == oid
    signups = client.get(f"/api/opportunities/{oid}/signups", headers=org["h"]).json()
    assert signups[0]["volunteer"]["id"] == vol["id"]


def test_cancel_signup_after_start_rejected(client):
    oid = new_opportunity(client, make_org(client)).json()["id"]
    vol = make_user(client, "volunteer")
    signup(client, vol, oid)
    set_start_in_past(oid)
    assert client.delete(f"/api/opportunities/{oid}/signups/me", headers=vol["h"]).status_code == 409


def test_role_checks(client):
    org = make_org(client)
    oid = new_opportunity(client, org).json()["id"]
    res = make_user(client, "resident")
    assert signup(client, res, oid).status_code == 403
    assert new_opportunity(client, make_user(client, "volunteer")).status_code == 403
    assert client.get(f"/api/opportunities/{oid}/signups", headers=res["h"]).status_code == 403


def test_detail_shows_signup_state(client):
    oid = new_opportunity(client, make_org(client)).json()["id"]
    vol = make_user(client, "volunteer")
    signup(client, vol, oid)
    d = client.get(f"/api/opportunities/{oid}", headers=vol["h"]).json()
    assert d["is_signed_up"] is True and d["slots_taken"] == 1 and d["is_owner"] is False
    assert d["organization"]["org_name"].startswith("Shelter")
