"""Request lifecycle and limits (ported from the Alpha API probe)."""
from concurrent.futures import ThreadPoolExecutor

from conftest import make_user, new_request


def act(client, user, rid, action):
    return client.patch(f"/api/requests/{rid}/{action}", headers=user["h"])


def full_cycle(client, res, vol, rid):
    assert act(client, vol, rid, "claim").status_code == 200
    assert act(client, res, rid, "accept").status_code == 200
    assert act(client, vol, rid, "complete").json()["status"] == "completed"
    return act(client, res, rid, "confirm")


def test_happy_path(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    r = full_cycle(client, res, vol, rid)
    assert r.json()["status"] == "confirmed" and r.json()["closed_at"]


def test_map_shows_approx_without_address(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    items = client.get(
        "/api/map", params={"lat": 50.45, "lng": 30.52, "type": "request"}, headers=vol["h"]
    ).json()
    item = next(i for i in items if i["id"] == rid)
    assert (item["latitude"], item["longitude"]) != (50.4501, 30.5234)
    assert "address" not in item


def test_role_checks(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    assert new_request(client, vol).status_code == 403
    rid = new_request(client, res).json()["id"]
    assert act(client, res, rid, "claim").status_code == 403


def test_validation(client):
    res = make_user(client, "resident")
    assert new_request(client, res, category="weapons").status_code == 422
    assert new_request(client, res, description="   ").status_code == 422


def test_self_claim_rejected(client):
    both = make_user(client, "resident", "volunteer")
    rid = new_request(client, both).json()["id"]
    assert act(client, both, rid, "claim").status_code == 409


def test_active_request_limit(client):
    res = make_user(client, "resident")
    assert [new_request(client, res).status_code for _ in range(4)] == [201, 201, 201, 409]


def test_active_request_limit_concurrent(client):
    res = make_user(client, "resident")
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda _: new_request(client, res).status_code, range(8)))
    assert codes.count(201) == 3


def test_claim_limit_concurrent(client):
    res1, res2 = make_user(client, "resident"), make_user(client, "resident")
    rids = [new_request(client, res1).json()["id"] for _ in range(2)]
    rids.append(new_request(client, res2).json()["id"])
    vol = make_user(client, "volunteer")
    with ThreadPoolExecutor(3) as ex:
        codes = list(ex.map(lambda r: act(client, vol, r, "claim").status_code, rids))
    assert sorted(codes) == [200, 200, 409]


def test_two_volunteers_race(client):
    res = make_user(client, "resident")
    rid = new_request(client, res).json()["id"]
    a, b = make_user(client, "volunteer"), make_user(client, "volunteer")
    with ThreadPoolExecutor(2) as ex:
        codes = sorted(ex.map(lambda v: act(client, v, rid, "claim").status_code, (a, b)))
    assert codes == [200, 409]


def test_state_machine_abuse(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    assert act(client, res, rid, "reopen").status_code == 409
    act(client, res, rid, "accept")
    act(client, vol, rid, "complete")
    assert act(client, vol, rid, "release").status_code == 409


def test_reopen_returns_to_open(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    act(client, vol, rid, "claim")
    act(client, res, rid, "accept")
    act(client, vol, rid, "complete")
    r = act(client, res, rid, "reopen")
    assert r.json()["status"] == "open" and r.json()["accepted"] is False


def test_email_case_insensitive(client):
    user = make_user(client, "resident")
    r = client.post(
        "/api/auth/register",
        json={"email": user["email"].upper(), "password": "secret12", "display_name": "x", "is_resident": True},
    )
    assert r.status_code == 409
