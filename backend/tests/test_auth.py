import os
import subprocess
import sys
from pathlib import Path

from conftest import make_user

BACKEND = Path(__file__).resolve().parent.parent


def test_health_under_api(client):
    assert client.get("/api/health").status_code == 200


def test_register_login_me(client):
    user = make_user(client, "resident")
    r = client.get("/api/auth/me", headers=user["h"])
    assert r.status_code == 200
    assert r.json()["roles"] == ["resident"]


def test_missing_token_401(client):
    assert client.get("/api/auth/me").status_code == 401


def _run(args, env_overrides):
    env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"} | env_overrides
    return subprocess.run(
        [sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True
    )


def test_secret_required():
    r = _run(["-c", "import app.config"], {})
    assert r.returncode != 0
    assert "JWT_SECRET" in r.stderr


def test_short_secret_rejected():
    r = _run(["-c", "import app.config"], {"JWT_SECRET": "short"})
    assert r.returncode != 0
    assert "JWT_SECRET" in r.stderr


def test_seed_requires_password():
    r = _run(["-m", "app.seed", "--email", "m@x.com"], {"JWT_SECRET": "y" * 40})
    assert r.returncode != 0
    assert "password" in r.stderr
