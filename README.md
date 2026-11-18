# Razom

A mutual-aid map web platform connecting residents who need help with volunteers and verified organizations — built for war / blackout conditions where needs (charging a phone, delivering water/medicine, walking shelter dogs) are scattered across chats and lost in minutes.

> **Team:** Uliana Matviienko, Bogdan Borachuk
> **Stack:** FastAPI · PostgreSQL + PostGIS · JWT auth · Leaflet (HTML) frontend

This repository is at the **Beta** stage (Stage 3): the backend is complete; the new frontend is in progress. The Alpha is described in [`Alpha Version Report.md`](./Alpha%20Version%20Report.md).

---

## Quick start

### Prerequisites
- Docker (for PostgreSQL+PostGIS) **or** a local Postgres with the `postgis` extension
- Python 3.12

### 1. Start the database
```bash
docker compose up -d db
```
This runs `postgis/postgis:16-3.4` on host port **5433** (so it doesn't clash with a locally installed PostgreSQL). The schema is created by Alembic when the backend starts.

### 2. Run the backend (it also serves the frontend)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg2://razom:razom@localhost:5433/razom"
# required, at least 32 characters; the app refuses to start without it
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn app.main:app --reload --port 8000
```

### 3. Seed the first moderator
```bash
python -m app.seed --email admin@razom.local --password <at-least-8-chars>
```

### Tests
```bash
cd backend
pip install -r requirements-dev.txt
pytest
```
Tests use a separate database `razom_test` on the same server (created automatically).

### 4. Demo data (development only)
```bash
python -m app.demo_seed
```
Creates one account per role (resident, volunteer, approved and pending organization, moderator; password `demo-pass-123`) plus requests and opportunities in Kyiv. Refuses to run on a database with real users.

### 5. Open the app
- **API docs (Swagger):** http://localhost:8000/docs
- **Frontend:** the Beta frontend is being built in `frontend/` (Vite). `npm run build` writes `frontend/dist`, which the backend serves at http://localhost:8000. The API contract for it is in [`docs/FRONTEND-API.md`](./docs/FRONTEND-API.md).

---

## Project structure
```
razom-sdt-208/
├── docker-compose.yml              # PostGIS database (host port 5433)
├── docs/FRONTEND-API.md            # API guide for the frontend
├── backend/
│   ├── requirements.txt  requirements-dev.txt  alembic.ini  pytest.ini
│   ├── app/
│   │   ├── main.py                 # app, /api routers, security headers, serves frontend/dist
│   │   ├── config.py database.py models.py schemas.py security.py deps.py geo.py
│   │   ├── privacy.py              # who may see a request's exact address (+ access log)
│   │   ├── claims.py               # claim expiry, releasing a blocked volunteer's claims
│   │   ├── moderation_rules.py     # reports, 3-report auto-hide, restore
│   │   ├── stats.py retention.py ratelimit.py
│   │   ├── seed.py demo_seed.py    # first moderator / demo data
│   │   ├── migrations/             # Alembic: 0001 baseline, 0002 beta, 0003 review fixes
│   │   └── routers/                # auth, requests, me, map, opportunities, reports, moderation
│   └── tests/                      # pytest against a real PostGIS test database
└── frontend/                       # web client (being replaced by the Beta frontend)
```

## Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://razom:razom@localhost:5433/razom` | Postgres connection |
| `JWT_SECRET` | *(none, required, ≥ 32 chars)* | JWT signing secret |
| `CORS_ORIGINS` | *(empty = CORS off)* | Comma-separated allowed origins; not needed with the Vite proxy |
| `RATE_LIMIT_ENABLED` | `true` | Per-IP rate limits on login, register, new requests, reports |
| `BCRYPT_ROUNDS` | `12` | Password hashing cost (tests lower it) |

## License / scope
This is a university capstone project (MIT license). Scope and out-of-scope items are described in the proposal and the Alpha/Beta reports.
