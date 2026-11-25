"""Verified badge, profile photos (who may see whose) and "verified only"."""
from conftest import (
    claim_ref,
    make_moderator,
    make_org,
    make_user,
    make_verified,
    new_opportunity,
    new_request,
)

MAP = {"lat": 50.45, "lng": 30.52}


def photo(client, owner, viewer):
    return client.get(f"/api/users/{owner['id']}/photo", headers=viewer["h"])


def statuses(client, pairs):
    return [photo(client, owner, viewer).status_code for owner, viewer in pairs]


def map_items(client, user, **params):
    r = client.get("/api/map", params=MAP | params, headers=user["h"])
    assert r.status_code == 200, r.text
    return r.json()


def verified_pair(client):
    mod = make_moderator(client)
    res, vol = make_user(client, "resident"), make_user(client, "volunteer")
    make_verified(client, res, mod)
    make_verified(client, vol, mod)
    return mod, res, vol


def test_photo_access_matrix(client):
    mod, res, vol = verified_pair(client)
    stranger = make_user(client, "volunteer")
    rid = new_request(client, res).json()["id"]

    assert statuses(client, [(res, vol), (vol, res), (res, stranger), (vol, stranger)]) == [404] * 4
    assert statuses(client, [(res, res), (vol, vol), (res, mod), (vol, mod)]) == [200] * 4

    assert client.patch(f"/api/requests/{rid}/claim", headers=vol["h"]).status_code == 200
    assert statuses(client, [(vol, res), (res, vol), (res, stranger)]) == [200, 404, 404]

    r = client.patch(f"/api/requests/{rid}/accept", headers=res["h"], json=claim_ref(client, res, rid))
    assert r.status_code == 200
    assert statuses(client, [(res, vol), (vol, res), (vol, stranger)]) == [200, 200, 404]

    assert client.patch(f"/api/requests/{rid}/complete", headers=vol["h"]).status_code == 200
    assert statuses(client, [(res, vol), (vol, res)]) == [404, 200]


def test_photo_unknown_or_unverified_is_404(client):
    u = make_user(client, "resident")
    assert client.get("/api/users/999999/photo", headers=u["h"]).status_code == 404
    r = photo(client, u, u)
    assert r.status_code == 404
    # same body as "not allowed", so a 404 never says whether a photo exists
    assert r.json() == client.get("/api/users/999999/photo", headers=u["h"]).json()


def test_photo_headers_and_csp(client):
    mod, res, _ = verified_pair(client)
    r = photo(client, res, res)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff"
    assert "no-store" in r.headers["cache-control"] and "private" in r.headers["cache-control"]
    img_src = next(
        d for d in r.headers["content-security-policy"].split(";") if d.strip().startswith("img-src")
    )
    assert "blob:" in img_src


def test_badge_fields(client):
    mod, res, vol = verified_pair(client)
    org = make_org(client)
    rid = new_request(client, res).json()["id"]
    oid = new_opportunity(client, org).json()["id"]

    me = client.get("/api/auth/me", headers=res["h"]).json()
    assert me["is_verified"] is True and me["only_verified_residents"] is False

    items = {(i["type"], i["id"]): i for i in map_items(client, vol)}
    assert items[("request", rid)]["author_verified"] is True
    assert items[("request", rid)]["verified_only"] is False
    assert items[("opportunity", oid)]["author_verified"] is None
    assert items[("opportunity", oid)]["verified_only"] is None

    client.patch(f"/api/requests/{rid}/claim", headers=vol["h"])
    seen = client.get(f"/api/requests/{rid}", headers=vol["h"]).json()
    assert seen["author_verified"] is True and seen["verified_only"] is False
    assert seen["author_photo_url"] is None  # not accepted yet

    claimer = client.get(f"/api/requests/{rid}", headers=res["h"]).json()["claimer"]
    assert claimer["user_id"] == vol["id"] and claimer["is_verified"] is True
    assert claimer["photo_url"] == f"/api/users/{vol['id']}/photo"

    client.patch(f"/api/requests/{rid}/accept", headers=res["h"], json=claim_ref(client, res, rid))
    seen = client.get(f"/api/requests/{rid}", headers=vol["h"]).json()
    assert seen["author_photo_url"] == f"/api/users/{res['id']}/photo"
    # the author's own view never carries their photo url
    assert client.get(f"/api/requests/{rid}", headers=res["h"]).json()["author_photo_url"] is None

    # an unverified volunteer: no badge, no photo url
    res2, vol2 = make_user(client, "resident"), make_user(client, "volunteer")
    rid2 = new_request(client, res2).json()["id"]
    assert client.get(f"/api/requests/{rid2}", headers=vol2["h"]).json()["author_verified"] is False
    client.patch(f"/api/requests/{rid2}/claim", headers=vol2["h"])
    claimer = client.get(f"/api/requests/{rid2}", headers=res2["h"]).json()["claimer"]
    assert claimer["is_verified"] is False and claimer["photo_url"] is None


def test_verified_only_claim(client):
    mod = make_moderator(client)
    res = make_user(client, "resident")
    plain, checked = make_user(client, "volunteer"), make_user(client, "volunteer")
    make_verified(client, checked, mod)
    r = new_request(client, res, verified_only=True)
    assert r.status_code == 201 and r.json()["verified_only"] is True
    rid = r.json()["id"]
    assert next(i for i in map_items(client, plain) if i["id"] == rid)["verified_only"] is True

    r = client.patch(f"/api/requests/{rid}/claim", headers=plain["h"])
    assert r.status_code == 403
    assert r.json() == {"detail": "This request is for verified volunteers only"}
    assert client.patch(f"/api/requests/{rid}/claim", headers=checked["h"]).status_code == 200
    # the verified-only answer comes before "no longer open", so it never reveals the status
    assert client.patch(f"/api/requests/{rid}/claim", headers=plain["h"]).status_code == 403


def test_only_verified_residents_filter(client):
    mod = make_moderator(client)
    checked_res, plain_res = make_user(client, "resident"), make_user(client, "resident")
    vol = make_user(client, "volunteer")
    make_verified(client, checked_res, mod)
    good = new_request(client, checked_res).json()["id"]
    plain = new_request(client, plain_res).json()["id"]
    oid = new_opportunity(client, make_org(client)).json()["id"]

    got = {(i["type"], i["id"]) for i in map_items(client, vol)}
    assert got == {("request", good), ("request", plain), ("opportunity", oid)}

    r = client.patch("/api/me/settings", headers=vol["h"], json={"only_verified_residents": True})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=vol["h"]).json()["only_verified_residents"] is True
    got = {(i["type"], i["id"]) for i in map_items(client, vol)}
    assert got == {("request", good), ("opportunity", oid)}


def test_lapsed_claim_hides_volunteer_photo(client):
    from sqlalchemy import text

    from app.database import engine

    _, res, vol = verified_pair(client)
    rid = new_request(client, res).json()["id"]
    client.patch(f"/api/requests/{rid}/claim", headers=vol["h"])
    assert photo(client, vol, res).status_code == 200
    with engine.begin() as conn:  # the resident never accepted within the window
        conn.execute(
            text("UPDATE help_requests SET claimed_at = now() - interval '13 hours' WHERE id = :i"),
            {"i": rid},
        )
    assert photo(client, vol, res).status_code == 404
