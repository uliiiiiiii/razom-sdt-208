"""Address protection: acceptance before reveal, access log, 404 rules, retention."""
from sqlalchemy import text

from app.database import engine
from app.retention import purge_closed_addresses
from conftest import claim_ref, make_user, new_request


def act(client, user, rid, action):
    body = claim_ref(client, user, rid) if action in ("accept", "decline") else None
    return client.patch(f"/api/requests/{rid}/{action}", headers=user["h"], json=body)


def get(client, user, rid):
    return client.get(f"/api/requests/{rid}", headers=user["h"])


def setup_claimed(client):
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]
    assert act(client, vol, rid, "claim").status_code == 200
    return res, vol, rid


def access_rows(rid):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT user_id, via FROM address_access_log WHERE request_id = :r"), {"r": rid}
        ).all()


def test_claim_does_not_reveal_address(client):
    _, vol, rid = setup_claimed(client)
    d = get(client, vol, rid).json()
    assert d["address"] is None
    assert d["exact_location"] is False
    assert d["accepted"] is False
    assert d["is_claimer"] is True


def test_accept_reveals_and_logs(client):
    res, vol, rid = setup_claimed(client)
    assert act(client, res, rid, "accept").status_code == 200
    d = get(client, vol, rid).json()
    assert d["address"] == "Khreshchatyk 1, apt 5"
    assert d["exact_location"] is True
    assert access_rows(rid) == [(vol["id"], "claim")]


def test_author_view_not_logged(client):
    res, _, rid = setup_claimed(client)
    assert get(client, res, rid).json()["address"] == "Khreshchatyk 1, apt 5"
    assert access_rows(rid) == []


def test_author_sees_claimer_info(client):
    res, vol, rid = setup_claimed(client)
    d = get(client, res, rid).json()
    assert d["claimer"]["display_name"].startswith("User")
    assert d["claimer"]["confirmed_count"] == 0
    assert get(client, vol, rid).json()["claimer"] is None


def test_only_author_can_accept(client):
    _, vol, rid = setup_claimed(client)
    assert act(client, vol, rid, "accept").status_code == 403


def test_decline_blocks_reclaim(client):
    res, vol, rid = setup_claimed(client)
    r = act(client, res, rid, "decline")
    assert r.status_code == 200 and r.json()["status"] == "open"
    assert act(client, vol, rid, "claim").status_code == 409
    other = make_user(client, "volunteer")
    assert act(client, other, rid, "claim").status_code == 200


def test_cannot_decline_after_accept(client):
    res, _, rid = setup_claimed(client)
    act(client, res, rid, "accept")
    assert act(client, res, rid, "decline").status_code == 409


def test_ex_claimer_loses_access(client):
    res, vol, rid = setup_claimed(client)
    act(client, res, rid, "accept")
    assert act(client, vol, rid, "release").status_code == 200
    d = get(client, vol, rid).json()
    assert d["address"] is None and d["accepted"] is False

    rid2 = new_request(client, res).json()["id"]
    act(client, vol, rid2, "claim")
    act(client, res, rid2, "accept")
    assert act(client, res, rid2, "cancel").status_code == 200
    assert get(client, vol, rid2).status_code == 404


def test_claim_rate_limit_24h(client):
    vol = make_user(client, "volunteer")
    residents = [make_user(client, "resident") for _ in range(2)]
    rids = [new_request(client, residents[i % 2]).json()["id"] for i in range(6)]
    for rid in rids[:5]:
        assert act(client, vol, rid, "claim").status_code == 200
        assert act(client, vol, rid, "release").status_code == 200
    r = act(client, vol, rids[5], "claim")
    assert r.status_code == 409
    assert "24" in r.json()["detail"]


def test_complete_requires_accept(client):
    _, vol, rid = setup_claimed(client)
    assert act(client, vol, rid, "complete").status_code == 409


def test_closed_hidden_from_strangers(client):
    res, vol, rid = setup_claimed(client)
    act(client, res, rid, "accept")
    act(client, vol, rid, "complete")
    assert act(client, res, rid, "confirm").json()["status"] == "confirmed"
    stranger = make_user(client, "volunteer")
    assert get(client, stranger, rid).status_code == 404
    assert get(client, res, rid).status_code == 200
    d = get(client, vol, rid)
    assert d.status_code == 200 and d.json()["address"] is None


def test_hidden_request_404_for_strangers(client):
    res = make_user(client, "resident")
    rid = new_request(client, res).json()["id"]
    with engine.begin() as conn:
        conn.execute(text("UPDATE help_requests SET is_hidden = true WHERE id = :r"), {"r": rid})
    assert get(client, make_user(client, "volunteer"), rid).status_code == 404
    assert get(client, res, rid).status_code == 200


def test_no_author_id_in_responses(client):
    res, vol, rid = setup_claimed(client)
    for body in (get(client, vol, rid).json(), get(client, res, rid).json()):
        assert "author_id" not in body and "claimed_by" not in body
    items = client.get(
        "/api/map", params={"lat": 50.45, "lng": 30.52, "type": "request"}, headers=vol["h"]
    ).json()
    assert all("author_id" not in i for i in items)


def test_purge_closed_addresses(client, db):
    res, vol, rid = setup_claimed(client)
    act(client, res, rid, "accept")
    act(client, vol, rid, "complete")
    act(client, res, rid, "confirm")
    recent = new_request(client, res).json()["id"]
    act(client, res, recent, "cancel")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE help_requests SET closed_at = now() - interval '31 days' WHERE id = :r"),
            {"r": rid},
        )
        conn.execute(
            text("UPDATE help_requests SET closed_at = now() - interval '5 days' WHERE id = :r"),
            {"r": recent},
        )
    assert purge_closed_addresses(db) == 1
    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT id, address IS NULL AND ST_Equals(location::geometry, approx_location::geometry) "
                    "FROM help_requests"
                )
            ).all()
        )
    assert rows == {rid: True, recent: False}


def test_me_lists(client):
    res, vol, rid = setup_claimed(client)
    new_request(client, res)
    mine = client.get("/api/me/requests", headers=res["h"])
    assert mine.status_code == 200 and len(mine.json()) == 2
    claims = client.get("/api/me/claims", headers=vol["h"])
    assert [c["id"] for c in claims.json()] == [rid]
    assert client.get("/api/me/requests", headers=vol["h"]).status_code == 403
    assert client.get("/api/me/claims", headers=res["h"]).status_code == 403
