"""Abuse hardening: rate limits, security headers, CORS (S7, S8)."""
import pytest

from app.ratelimit import limiter
from conftest import make_user

CSP = (
    "default-src 'self'; img-src 'self' data: https://*.tile.openstreetmap.org; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'"
)


@pytest.fixture
def rate_limited():
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


@pytest.mark.parametrize("path", ["/api/health", "/"])
def test_security_headers(client, path):
    r = client.get(path)
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_login_rate_limit(client, rate_limited):
    body = {"email": "nobody@test.com", "password": "wrong-password"}
    responses = [client.post("/api/auth/login", json=body) for _ in range(11)]
    assert [r.status_code for r in responses[:10]] == [401] * 10
    assert responses[10].status_code == 429
    assert "Too many requests" in responses[10].json()["detail"]


def test_register_rate_limit(client, rate_limited):
    def register(i):
        body = {"email": f"r{i}@test.com", "password": "secret12", "display_name": "R", "is_volunteer": True}
        return client.post("/api/auth/register", json=body).status_code

    assert [register(i) for i in range(6)] == [201] * 5 + [429]


def test_create_request_rate_limit(client, rate_limited):
    user = make_user(client, "resident")
    body = {"category": "water", "description": "x", "latitude": 50.45, "longitude": 30.52}
    codes = [client.post("/api/requests", json=body, headers=user["h"]).status_code for _ in range(11)]
    assert codes[-1] == 429


def test_no_cors_by_default(client):
    r = client.options(
        "/api/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in r.headers
