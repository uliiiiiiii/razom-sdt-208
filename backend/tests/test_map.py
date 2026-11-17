"""Combined radius search over requests and opportunities (FR 21-23)."""
from sqlalchemy import text

from app.database import engine
from conftest import make_org, make_user, new_opportunity, new_request

CENTER = {"lat": 50.45, "lng": 30.52}


def search(client, user, **params):
    return client.get("/api/map", params=CENTER | params, headers=user["h"])


def sql(stmt, **params):
    with engine.begin() as conn:
        conn.execute(text(stmt), params)


def test_map_mixes_types_sorted(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res, latitude=50.4501, longitude=30.5201).json()["id"]
    oid = new_opportunity(client, make_org(client), latitude=50.47, longitude=30.52).json()["id"]
    items = search(client, vol).json()
    assert [(i["type"], i["id"]) for i in items] == [("request", rid), ("opportunity", oid)]
    assert items[0]["distance_m"] <= items[1]["distance_m"]
    assert items[1]["slots_left"] == 2 and items[1]["start_time"]
    assert items[0]["slots_left"] is None and "address" not in items[0]


def test_map_request_point_is_approximate(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    new_request(client, res)
    item = search(client, vol, type="request").json()[0]
    assert (item["latitude"], item["longitude"]) != (50.4501, 30.5234)


def test_map_type_filter(client):
    new_request(client, make_user(client, "resident"))
    new_opportunity(client, make_org(client))
    vol = make_user(client, "volunteer")
    assert {i["type"] for i in search(client, vol, type="request").json()} == {"request"}
    assert {i["type"] for i in search(client, vol, type="opportunity").json()} == {"opportunity"}
    assert len(search(client, vol, type="all").json()) == 2


def test_map_category_filter(client):
    res = make_user(client, "resident")
    new_request(client, res, category="water")
    new_request(client, res, category="medicine")
    new_opportunity(client, make_org(client), category="pets")
    items = search(client, make_user(client, "volunteer"), category="medicine").json()
    assert [i["category"] for i in items] == ["medicine"]


def test_map_excludes_hidden_and_blocked(client):
    vol = make_user(client, "volunteer")
    visible = new_request(client, make_user(client, "resident")).json()["id"]
    hidden = new_request(client, make_user(client, "resident")).json()["id"]
    blocked_author = make_user(client, "resident")
    of_blocked = new_request(client, blocked_author).json()["id"]
    sql("UPDATE help_requests SET is_hidden = true WHERE id = :i", i=hidden)
    sql("UPDATE users SET is_blocked = true WHERE id = :i", i=blocked_author["id"])

    org = make_org(client)
    ok_opp = new_opportunity(client, org).json()["id"]
    hidden_opp = new_opportunity(client, org).json()["id"]
    past_opp = new_opportunity(client, org).json()["id"]
    closed_opp = new_opportunity(client, org).json()["id"]
    sql("UPDATE opportunities SET is_hidden = true WHERE id = :i", i=hidden_opp)
    sql("UPDATE opportunities SET start_time = now() - interval '1 hour' WHERE id = :i", i=past_opp)
    sql("UPDATE opportunities SET status = 'closed' WHERE id = :i", i=closed_opp)
    pending_org = make_org(client)
    revoked = new_opportunity(client, pending_org).json()["id"]
    sql("UPDATE organizations SET verification_status = 'rejected' WHERE id = :i", i=pending_org["org_id"])

    got = {(i["type"], i["id"]) for i in search(client, vol).json()}
    assert got == {("request", visible), ("opportunity", ok_opp)}
    assert ("opportunity", revoked) not in got and ("request", of_blocked) not in got


def test_map_radius_bounds(client):
    vol = make_user(client, "volunteer")
    assert search(client, vol, radius=0).status_code == 422
    assert search(client, vol, radius=50001).status_code == 422
    assert search(client, vol, type="people").status_code == 422


def test_map_requires_login(client):
    assert client.get("/api/map", params=CENTER).status_code == 401


def test_old_requests_map_removed(client):
    vol = make_user(client, "volunteer")
    assert client.get("/api/requests/map", params=CENTER, headers=vol["h"]).status_code != 200
