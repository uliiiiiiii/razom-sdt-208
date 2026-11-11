# Razom

A mutual-aid map web platform connecting residents who need help with volunteers and verified organizations — built for war / blackout conditions where needs (charging a phone, delivering water/medicine, walking shelter dogs) are scattered across chats and lost in minutes.

> **Team:** Uliana Matviienko, Bogdan Borachuk
> **Stack:** FastAPI · PostgreSQL + PostGIS · JWT auth · Leaflet (HTML) frontend

This repository contains the **Alpha prototype** (Stage 2). See [`Alpha Version Report.md`](./Alpha%20Version%20Report.md)

---

## Quick start

### Prerequisites
- Docker (for PostgreSQL+PostGIS) **or** a local Postgres with the `postgis` extension
- Python 3.11+

### 1. Start the database
```bash
docker compose up -d db
```
This runs `postgis/postgis:16-3.4` and applies `db/init.sql` automatically.

### 2. Run the backend (it also serves the frontend)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg2://razom:razom@localhost:5432/razom"
export JWT_SECRET="dev-secret-change-me"
uvicorn app.main:app --reload --port 8000
```

### 3. Seed the first moderator (optional, for later moderation features)
```bash
python -m app.seed --email admin@razom.local --password admin123
```

### 4. Open the app
Visit **http://localhost:8000/index.html**

> The FastAPI app serves the `frontend/` directory at `/`, so the whole Alpha runs from one process. API docs (Swagger) are at `/docs`.

---

## Running the end-to-end scenario

1. **Register** a resident at `/register.html` (tick *Resident*) → auto-logged in.
2. Click **+ New request**, pick a point on the map, choose a category, describe the need, submit.
3. In another browser / incognito, **register a volunteer** (tick *Volunteer*) → logged in.
4. On the map, click **Use map center** then **Search this area**. You should see the resident's request as a marker (approximate location).
5. Click the marker → **View details**. Note: the exact address is **hidden** for the volunteer here.
6. Click **Claim this request**. The status becomes `claimed`; now the volunteer **sees the exact location and address**.
7. Click **Mark completed** → status `completed`.
8. Switch back to the resident. Open the same request → click **Confirm received** → status `confirmed`.

That is the full lifecycle: `open → claimed → completed → confirmed`, screen to database and back.

---

## Project structure
```
razom-sdt-208/
├── db/init.sql                 # full PostgreSQL+PostGIS schema (design + implemented)
├── docker-compose.yml          # PostGIS database
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # FastAPI app (also serves frontend)
│       ├── config.py  database.py  models.py  schemas.py
│       ├── security.py  deps.py  geo.py
│       ├── seed.py              # first moderator
│       └── routers/
│           ├── auth.py          # register / login / me (JWT)
│           └── requests.py      # request lifecycle + PostGIS map + privacy
└── frontend/                   # HTML + Leaflet (also the UX/UI prototype)
    ├── index.html  login.html  register.html  create.html
    ├── css/style.css
    └── js/app.js
```

> **Note on the frontend:** the Alpha frontend is a plain static prototype — HTML pages plus a single shared `js/app.js`, with no framework, no build step, and `innerHTML`-based rendering. This is a deliberate shortcut to get a runnable end-to-end demo from one `uvicorn` process; it is **not production-grade**. The single `app.js` conflates the API client, auth state, and UI helpers that should be separate modules. Stage 3 replaces it with a proper component-based frontend (Next.js/React or Vite) that talks to the same FastAPI JSON API — no backend changes required. See the "Frontend architecture note" in [`Alpha Version Report.md`](./Alpha%20Version%20Report.md)

## Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://razom:razom@localhost:5432/razom` | Postgres connection |
| `JWT_SECRET` | `dev-secret-change-me` | JWT signing secret |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |

## License / scope
This is a university capstone project (MIT license). Scope and out-of-scope items are described in the proposal and the Alpha report.
