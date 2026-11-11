"""Application configuration (env-driven)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    cors_origins: tuple[str, ...] = ("*",)


def get_settings() -> Settings:
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://razom:razom@localhost:5432/razom",
    )
    secret = os.getenv("JWT_SECRET", "dev-secret-change-me")
    cors = os.getenv("CORS_ORIGINS", "*")
    return Settings(
        database_url=db_url,
        jwt_secret=secret,
        cors_origins=tuple(o.strip() for o in cors.split(",")) if cors else ("*",),
    )


settings = get_settings()
