"""Application configuration (env-driven)."""
from __future__ import annotations

import os
from dataclasses import dataclass

MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    verification_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    cors_origins: tuple[str, ...] = ()
    bcrypt_rounds: int = 12
    rate_limit_enabled: bool = True


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
    verification_key = os.getenv("VERIFICATION_KEY", "")
    if len(verification_key) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            f"VERIFICATION_KEY must be set to a random string of at least {MIN_SECRET_LENGTH} characters"
        )
    cors = os.getenv("CORS_ORIGINS", "")
    return Settings(
        database_url=db_url,
        jwt_secret=secret,
        verification_key=verification_key,
        cors_origins=tuple(o.strip() for o in cors.split(",") if o.strip()),
        # lower only in tests, to keep the suite fast
        bcrypt_rounds=int(os.getenv("BCRYPT_ROUNDS", "12")),
        rate_limit_enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false",
    )


settings = get_settings()
