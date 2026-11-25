"""Per-IP rate limits against password guessing, mass sign-ups and spam.

Limits are in-memory, so they reset on restart and aren't shared between
processes; fine for a single uvicorn process. Behind a reverse proxy, run
uvicorn with --proxy-headers so the client IP is used, not the proxy's.

Routers that use @limiter.limit must NOT use `from __future__ import
annotations`: slowapi's wrapper then hides the type hints from FastAPI and
the request body is mistaken for a query parameter.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import settings

LOGIN_LIMIT = "10/minute"
REGISTER_LIMIT = "5/hour"
CREATE_REQUEST_LIMIT = "10/hour"
REPORT_LIMIT = "20/hour"
VERIFICATION_START_LIMIT = "10/hour"
VERIFICATION_SUBMIT_LIMIT = "5/hour"

limiter = Limiter(key_func=get_remote_address, enabled=settings.rate_limit_enabled)


def rate_limit_exceeded(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Same error shape as the rest of the API: {"detail": ...}."""
    return JSONResponse(
        status_code=429, content={"detail": f"Too many requests: limit is {exc.detail}"}
    )
