"""FastAPI application entry point.

At startup Alembic upgrades the database to the latest schema. All JSON
routes live under /api; API docs at /docs; every other GET is the built
frontend (frontend/dist), with index.html for client-side routes.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi.errors import RateLimitExceeded

from .config import settings
from .database import SessionLocal
from .migrate import upgrade_to_head
from .ratelimit import limiter, rate_limit_exceeded
from .retention import purge_closed_addresses
from .verification import expire_stale
from .routers import auth, map, me, moderation, opportunities, reports, requests, verification


RETENTION_INTERVAL_SECONDS = 24 * 3600


def _purge() -> None:
    with SessionLocal() as db:
        purge_closed_addresses(db)
        expire_stale(db)


async def _purge_daily() -> None:
    # the server may run for weeks; the 30-day retention must still happen
    while True:
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
        await asyncio.to_thread(_purge)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    upgrade_to_head(settings.database_url)
    _purge()
    task = asyncio.create_task(_purge_daily())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Razom API", version="0.2.0-beta", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded)

# Same-origin only: scripts, styles and API calls from this server; map tiles
# from OpenStreetMap; blob: for protected photos the page fetches with its
# token (only the page's own scripts can create blob URLs). Limits the damage
# any XSS bug could do with the token.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'"
)
# Swagger/ReDoc load their UI from a CDN with inline scripts; they hold no user data
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith(DOCS_PATHS):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    # OSM tile servers refuse requests without a Referer; cross-site we send
    # only the origin, never a path
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


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
    return {"status": "ok", "service": "razom", "version": app.version}


api.include_router(auth.router)
api.include_router(requests.router)
api.include_router(me.router)
api.include_router(verification.router)
api.include_router(verification.moderation_router)
api.include_router(verification.users_router)
api.include_router(opportunities.router)
api.include_router(map.router)
api.include_router(reports.router)
api.include_router(moderation.router)
app.include_router(api)

# The built frontend (`npm run build` -> frontend/dist), so the whole app runs
# from one process. Only dist/ is served, never the frontend sources.
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, detail="Not Found")
    dist = FRONTEND_DIST.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise HTTPException(404, detail="Frontend not built (run `npm run build` in frontend/)")
    asset = (dist / path).resolve()
    if path and asset.is_file() and asset.is_relative_to(dist):
        return FileResponse(asset)
    return FileResponse(index)  # client-side route, e.g. /requests/5
