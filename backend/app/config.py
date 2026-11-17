"""Application configuration (env-driven)."""
from __future__ import annotations

import os
from dataclasses import dataclass

MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    cors_origins: tuple[str, ...] = ()


def get_settings() -> Settings:
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://razom:razom@localhost:5433/razom",
    )
    # No default: a known secret would let anyone forge tokens, moderators included.
    secret = os.getenv("JWT_SECRET", "")
    if len(secret) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET must be set to a random string of at least {MIN_SECRET_LENGTH} characters"
        )
    cors = os.getenv("CORS_ORIGINS", "")
    return Settings(
        database_url=db_url,
        jwt_secret=secret,
        cors_origins=tuple(o.strip() for o in cors.split(",") if o.strip()),
    )


settings = get_settings()
