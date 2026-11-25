"""Moderator lists page back with ?limit=&before=<id>, newest first."""
import pytest
from sqlalchemy import text

from app.database import engine
from conftest import make_moderator, make_user, new_request


def log_rows(client, n: int, rid: int | None = None) -> int:
    """n access-log rows for one request (a new one unless rid is given)."""
    if rid is None:
        rid = new_request(client, make_user(client, "resident")).json()["id"]
    vol = make_user(client, "volunteer")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO address_access_log (request_id, user_id, via) "
                "SELECT :r, :u, 'claim' FROM generate_series(1, :n)"
            ),
            {"r": rid, "u": vol["id"], "n": n},
        )
    return rid


def ids(client, mod, url="/api/moderation/access-log", **params) -> list[int]:
    r = client.get(url, params=params, headers=mod["h"])
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()]


def test_access_log_reads_past_200(client):
    mod = make_moderator(client)
    log_rows(client, 230)
    seen, page = [], ids(client, mod, limit=200)
    while page:
        seen += page
        if len(page) < 200:
            break
        page = ids(client, mod, limit=200, before=page[-1])
    assert len(seen) == 230 == len(set(seen))
    assert seen == sorted(seen, reverse=True)


def test_access_log_default_page_is_50_newest_first(client):
    mod = make_moderator(client)
    log_rows(client, 60)
    assert ids(client, mod) == list(range(60, 10, -1))


def test_page_stable_when_rows_arrive(client):
    mod = make_moderator(client)
    rid = log_rows(client, 10)
    assert ids(client, mod, limit=4) == [10, 9, 8, 7]
    log_rows(client, 3, rid)
    assert ids(client, mod, limit=4, before=7) == [6, 5, 4, 3]


def test_before_unknown_id_and_end_of_list(client):
    mod = make_moderator(client)
    log_rows(client, 5)
    assert ids(client, mod, before=999) == [5, 4, 3, 2, 1]
    assert ids(client, mod, before=1) == []


def test_cursor_combines_with_request_filter(client):
    mod = make_moderator(client)
    first = log_rows(client, 1)
    second = log_rows(client, 1)
    for _ in range(2):  # interleave: ids 3..6 alternate between the requests
        log_rows(client, 1, first)
        log_rows(client, 1, second)
    mine = ids(client, mod, request_id=first)
    assert mine == [5, 3, 1]
    assert ids(client, mod, request_id=first, before=mine[0]) == [3, 1]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"before": 0}])
def test_limit_bounds(client, params):
    mod = make_moderator(client)
    r = client.get("/api/moderation/access-log", params=params, headers=mod["h"])
    assert r.status_code == 422
