from collections import Counter

import pytest

from app.demo_seed import DEMO_ACCOUNTS, DEMO_PASSWORD, generated_requests, seed_demo
from app.models import User
from app.security import hash_password
from conftest import make_user

CATEGORIES = {"charging", "groceries", "medicine", "water", "transport", "pets", "other"}


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, email
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_seed_creates_one_account_per_role(client, db):
    seed_demo(db)
    roles = {
        email: client.get("/api/auth/me", headers=login(client, email)).json()["roles"]
        for email in ("resident@razom.demo", "volunteer@razom.demo", "moderator@razom.demo")
    }
    assert roles["resident@razom.demo"] == ["resident"]
    assert roles["volunteer@razom.demo"] == ["volunteer"]
    assert roles["moderator@razom.demo"] == ["moderator"]
    pending = client.get("/api/me/organization", headers=login(client, "pending-org@razom.demo")).json()
    assert pending["verification_status"] == "pending"


def test_generated_requests_are_deterministic_and_varied():
    reqs = generated_requests()
    assert reqs == generated_requests()
    assert len(reqs) == 40
    assert {r["category"] for r in reqs} == CATEGORIES
    assert max(Counter(r["author_index"] for r in reqs).values()) <= 3
    assert sum(r["age_hours"] < 6 for r in reqs) >= 13


def test_seed_fills_the_map(client, db):
    seed_demo(db)
    items = client.get(
        "/api/map",
        params={"lat": 50.45, "lng": 30.52, "radius": 50000, "type": "request"},
        headers=login(client, "volunteer@razom.demo"),
    ).json()
    assert len(items) >= 35
    assert {i["category"] for i in items} == CATEGORIES
    assert all(50.35 <= i["latitude"] <= 50.55 and 30.40 <= i["longitude"] <= 30.70 for i in items)


@pytest.mark.parametrize("email", [e for e in DEMO_ACCOUNTS if e != "blocked@razom.demo"])
def test_every_named_account_logs_in(client, db, email):
    seed_demo(db)
    login(client, email)


def test_resumes_after_partial_seed(db):
    db.add(User(email="volunteer2@razom.demo", password_hash=hash_password(DEMO_PASSWORD),
                display_name="Half-seeded", is_volunteer=True))
    db.commit()
    seed_demo(db)
    assert db.query(User).filter_by(email="resident@razom.demo").one()


def test_seed_can_run_twice(db):
    seed_demo(db)
    seed_demo(db)  # starts over: no duplicate-email error


def test_seed_refuses_non_demo_database(client, db):
    make_user(client, "resident")
    with pytest.raises(RuntimeError):
        seed_demo(db)


def get(client, email, url, **params):
    r = client.get(url, params=params, headers=login(client, email))
    assert r.status_code == 200, r.text
    return r.json()


def test_resident_journey(client, db):
    seed_demo(db)
    mine = get(client, "resident@razom.demo", "/api/me/requests")
    assert Counter(r["status"] for r in mine) == Counter(
        open=1, claimed=1, completed=1, confirmed=1, cancelled=1
    )
    claimed = next(r for r in mine if r["status"] == "claimed")
    assert claimed["accepted"] is False
    assert claimed["claimer"]["display_name"] == "Taras (volunteer)"
    assert claimed["claimer"]["confirmed_count"] == 1
    claims = get(client, "volunteer@razom.demo", "/api/me/claims")
    accepted = [r for r in claims if r["status"] == "claimed" and r["accepted"]]
    assert len(accepted) == 1 and accepted[0]["address"]


def test_limits_hold_after_seed(client, db):
    from sqlalchemy import text

    seed_demo(db)
    over = db.execute(text(
        "SELECT (SELECT max(n) FROM (SELECT count(*) n FROM help_requests "
        "  WHERE status IN ('open','claimed','completed') GROUP BY author_id) a), "
        "(SELECT max(n) FROM (SELECT count(*) n FROM help_requests "
        "  WHERE status = 'claimed' GROUP BY claimed_by) c)"
    )).one()
    assert over[0] <= 3 and over[1] <= 2
    vol = login(client, "volunteer@razom.demo")
    open_id = get(client, "volunteer2@razom.demo", "/api/map", lat=50.45, lng=30.52,
                  radius=50000, type="request")[0]["id"]
    r = client.patch(f"/api/requests/{open_id}/claim", headers=vol)
    assert r.status_code == 409 and "cannot hold more than 2" in r.json()["detail"]
    r = client.post("/api/requests", headers=login(client, "resident16@razom.demo"), json={
        "category": "water", "description": "Need water", "latitude": 50.45, "longitude": 30.52,
    })
    assert r.status_code == 201, r.text


def test_unaccepted_claim_survives_map_load(client, db):
    seed_demo(db)
    get(client, "volunteer2@razom.demo", "/api/map", lat=50.45, lng=30.52)
    mine = get(client, "resident@razom.demo", "/api/me/requests")
    assert any(r["status"] == "claimed" and not r["accepted"] for r in mine)


def test_moderation_queue(client, db):
    seed_demo(db)
    reports = get(client, "moderator@razom.demo", "/api/moderation/reports")
    on_requests = [r for r in reports if r["target_type"] == "request"]
    assert len(on_requests) == 3 and {r["open_reports_on_target"] for r in on_requests} == {3}
    hidden_id = on_requests[0]["target_id"]
    on_map = get(client, "volunteer2@razom.demo", "/api/map", lat=50.45, lng=30.52, radius=50000)
    assert hidden_id not in {i["id"] for i in on_map if i["type"] == "request"}
    assert len([r for r in reports if r["target_type"] == "user"]) == 1
    r = client.post("/api/auth/login", json={"email": "blocked@razom.demo", "password": DEMO_PASSWORD})
    assert r.status_code == 403


def test_organizations_in_every_state(client, db):
    from datetime import datetime, timezone

    seed_demo(db)
    assert get(client, "pending-org@razom.demo", "/api/me/organization")["verification_status"] == "pending"
    rejected = get(client, "rejected-org@razom.demo", "/api/me/organization")
    assert rejected["verification_status"] == "rejected" and rejected["comment"]
    offers = get(client, "volunteer2@razom.demo", "/api/map", lat=50.45, lng=30.52,
                 radius=50000, type="opportunity")
    now = datetime.now(timezone.utc)
    assert any(o["slots_left"] == 0 for o in offers)
    assert all(datetime.fromisoformat(o["start_time"]) > now for o in offers)
    own = get(client, "org@razom.demo", "/api/me/opportunities")
    assert any(datetime.fromisoformat(o["start_time"]) < now for o in own)
    assert len(get(client, "volunteer@razom.demo", "/api/me/signups")) >= 2


def test_rerun_restores_the_demo_after_claims_expire(client, db):
    from sqlalchemy import text

    seed_demo(db)
    db.execute(text("UPDATE help_requests SET claimed_at = claimed_at - interval '13 hours'"))
    db.commit()
    get(client, "volunteer2@razom.demo", "/api/map", lat=50.45, lng=30.52)  # expires the claim
    seed_demo(db)
    mine = get(client, "resident@razom.demo", "/api/me/requests")
    assert any(r["status"] == "claimed" and not r["accepted"] for r in mine)


def test_seed_after_a_demo_email_registered_through_the_api(client, db):
    r = client.post("/api/auth/register", json={
        "email": "pending-org@razom.demo", "password": "secret12", "display_name": "X",
        "is_organization": True, "org_name": "Squatter",
    })
    assert r.status_code == 201
    seed_demo(db)
    assert get(client, "pending-org@razom.demo", "/api/me/organization")["org_name"] == "New Charity"


def test_verification_states_seeded(client, db):
    seed_demo(db)
    got = {e: get(client, f"{e}@razom.demo", "/api/me/verification")
           for e in ("volunteer", "resident", "volunteer2", "volunteer3", "volunteer4", "volunteer5")}
    assert {k: v["status"] for k, v in got.items()} == {
        "volunteer": "approved", "resident": "approved", "volunteer2": "pending",
        "volunteer3": "rejected", "volunteer4": "revoked", "volunteer5": "none"}
    assert got["volunteer3"]["comment"] == "The selfie does not show the challenge word."
    assert got["volunteer4"]["comment"] == "Document reported as stolen."


def test_moderator_can_review_seeded_submission(client, db):
    seed_demo(db)
    mod = login(client, "moderator@razom.demo")
    queue = get(client, "moderator@razom.demo", "/api/moderation/verifications")
    entry = next(q for q in queue if q["user"]["display_name"] == "Volunteer 2")
    for kind in ("id_document", "selfie", "profile"):
        r = client.get(f"/api/moderation/verifications/{entry['id']}/images/{kind}", headers=mod)
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert r.content[:2] == b"\xff\xd8"


def test_verified_only_requests_seeded(client, db):
    seed_demo(db)
    items = get(client, "volunteer@razom.demo", "/api/map", lat=50.45, lng=30.52,
                radius=50000, type="request")
    only = [i for i in items if i["verified_only"]]
    assert len(only) >= 4
    r = client.patch(f"/api/requests/{only[0]['id']}/claim", headers=login(client, "volunteer5@razom.demo"))
    assert r.status_code == 403
    vol_id = get(client, "volunteer@razom.demo", "/api/auth/me")["id"]
    r = client.get(f"/api/users/{vol_id}/photo", headers=login(client, "resident@razom.demo"))
    assert r.status_code == 200
