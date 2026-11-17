"""FastAPI application entry point.

At startup Alembic upgrades the database to the latest schema. All JSON
routes live under /api; everything else is the frontend.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .migrate import upgrade_to_head
from .routers import auth, requests


@asynccontextmanager
async def lifespan(_app: FastAPI):
    upgrade_to_head(settings.database_url)
    yield


app = FastAPI(title="Razom API", version="0.2.0-beta", lifespan=lifespan)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "razom", "version": "0.2.0-beta"}


api.include_router(auth.router)
api.include_router(requests.router)
app.include_router(api)

# Serve the frontend as static files when present, so the whole app can run
# from a single backend process.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
