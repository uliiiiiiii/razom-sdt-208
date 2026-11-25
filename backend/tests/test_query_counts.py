"""List endpoints must not run one query per row (N+1)."""
from contextlib import contextmanager

from sqlalchemy import event, text

from app.database import engine
from conftest import make_moderator, make_org, make_user, new_opportunity, new_request


@contextmanager
def queries():
    n = [0]

    def count(*_a, **_k):
        n[0] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        yield n
    finally:
        event.remove(engine, "before_cursor_execute", count)


def cost(client, url, user, rows):
    with queries() as n:
        r = client.get(url, headers=user["h"])
    assert r.status_code == 200 and len(r.json()) == rows, r.text
    return n[0]


def test_my_requests_history_is_constant(client):
    res = make_user(client, "resident")
    new_request(client, res)
    one = cost(client, "/api/me/requests", res, 1)
    for _ in range(2):
        new_request(client, res)
    with engine.begin() as conn:  # closed requests don't count against the active limit
        conn.execute(text("UPDATE help_requests SET status = 'cancelled'"))
    for _ in range(3):
        new_request(client, res)
    assert cost(client, "/api/me/requests", res, 6) == one


def test_moderation_report_list_is_constant(client):
    mod = make_moderator(client)

    def report_n(n):
        for _ in range(n):
            client.post("/api/reports", headers=make_user(client, "volunteer")["h"],
                        json={"target_type": "user", "target_id": make_user(client, "resident")["id"],
                              "reason": "spam spam"})

    report_n(1)
    one = cost(client, "/api/moderation/reports", mod, 1)
    report_n(5)
    assert cost(client, "/api/moderation/reports", mod, 6) == one


def test_my_opportunities_one_query_per_row_at_most(client):
    # ponytail: is_signed_up is still one query per row; batch it if orgs list hundreds
    org = make_org(client)
    new_opportunity(client, org)
    one = cost(client, "/api/me/opportunities", org, 1)
    for _ in range(4):
        new_opportunity(client, org)
    assert cost(client, "/api/me/opportunities", org, 5) <= one + 4
