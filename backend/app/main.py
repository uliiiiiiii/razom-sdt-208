"""FastAPI application entry point.

At startup we run db/init.sql against the real PostgreSQL+PostGIS database so
the implemented tables always match the design.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import engine
from .routers import auth, requests

INIT_SQL_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"


def run_init_sql() -> None:
    """Apply db/init.sql so the schema matches the design (idempotent)."""
    if not INIT_SQL_PATH.exists():
        return
    sql = INIT_SQL_PATH.read_text()
    with engine.begin() as conn:
        # psycopg2 executes a whole multi-statement script in one call and
        # correctly ignores comments (incl. semicolons inside -- comments).
        raw = conn.connection  # underlying DBAPI connection
        cur = raw.cursor()
        cur.execute(sql)
        raw.commit()


app = FastAPI(title="Razom API", version="0.1.0-alpha")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup() -> None:
    run_init_sql()


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "razom", "version": "0.1.0-alpha"}


app.include_router(auth.router)
app.include_router(requests.router)

# Serve the frontend (HTML + Leaflet) as static files when present, so the
# whole Alpha can run from a single backend process.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
