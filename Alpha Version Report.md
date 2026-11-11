**Razom — Alpha Version Report (Stage 2)**  
**Project:** Razom — a mutual-aid map connecting residents who need help with volunteers and verified organizations.  
   
 **Stage:** Alpha prototype  
   
 **Date:** November 2026  
  
---  
**Team members**  
  
|  |  |  
| - | - |  
| **Full name** |  **Role** |  
| **Uliana Matviienko** |  Code implementation (backend + frontend) |  
| **Bogdan Borachuk** |  Database architecture |  
  
   
  
---  
**1. Database design**  
The complete design lives in [`db/init.sql` (executable PostgreSQL + PostGIS schema) and is visualised in](./db/init.sql "./db/init.sql") [`docs/`. Same for the architecture and request flow.](./docs/ "./docs/")  
**Major entities and attributes**  
  
|  |  |  
| - | - |  
| **Entity** |  **Key attributes** |  
| **users** |  `id` (PK), `email` (unique), `password_hash`, `display_name`, `phone`, `is_resident`, `is_volunteer`, `is_organization`, `is_moderator`, `is_blocked`, `created_at` |  
| **organizations** |  `id` (PK), `user_id` (FK→users, unique), `org_name`, `description`, `verification_status` (pending/approved/rejected), `verified_at`, `verified_by` (FK→users), `created_at` |  
| **help_requests** |  `id` (PK), `author_id` (FK→users), `category`, `title`, `description`, `status`, `location` (PostGIS GEOGRAPHY POINT), `approx_location` (GEOGRAPHY POINT), `address`, `claimed_by` (FK→users), `claimed_at`, `created_at`, `updated_at` |  
| **opportunities** |  `id` (PK), `organization_id` (FK→organizations), `title`, `description`, `location` (GEOGRAPHY), `start_time`, `slots_total`, `status`, `created_at` |  
| **opportunity_signups** |  `id` (PK), `opportunity_id` (FK), `volunteer_id` (FK), `signed_up_at`, `attended` |  
| **reports** |  `id` (PK), `reporter_id` (FK), `target_type`, `target_id`, `reason`, `status`, `created_at` |  
| **verification_log** |  `id` (PK), `organization_id` (FK), `moderator_id` (FK), `decision`, `comment`, `created_at` |  
  
   
**Relationships and cardinalities**  
- **users 1—1 organizations**: an organization is a profile attached to a user with `is_organization = true`.  
- **users 1—N help_requests** (as `author_id`): a resident authors many requests.  
- **users 1—N help_requests** (as `claimed_by`): a volunteer claims many requests over time, but at most 2 concurrently (enforced in code).  
- **organizations 1—N opportunities**: an org publishes many opportunities.  
- **opportunities 1—N opportunity_signups**: each opportunity has sign-ups up to `slots_total`.  
- **users 1—N opportunity_signups** (as `volunteer_id`): a volunteer's history.  
- **users 1—N reports** (as `reporter_id`); **users 1—N verification_log** (as `moderator_id`).  
**Primary keys and foreign keys**  
- All tables use a `BIGSERIAL id` primary key.  
- Foreign keys reference `users(id)` and `organizations(id)` with `ON DELETE CASCADE` where the child is owned by the parent (requests, signups, reports, verification_log, organizations).  
**Constraints**  
- **Uniqueness:** `users.email`; `organizations.user_id`; `opportunity_signups(opportunity_id, volunteer_id)`; `reports(reporter_id, target_type, target_id)`.  
- **Not-null:** all `*_id` FKs, `password_hash`, `email`, `display_name`, `description` (requests), `location`, `slots_total`, `reason`, etc.  
- **CHECK constraints:** `help_requests.category` ∈ a fixed set; `help_requests.status` ∈ {open, claimed, completed, confirmed, cancelled}; `chk_claim_consistency` (a `claimed` request must have a claimer); `opportunities.slots_total > 0`; `opportunities.status`; `reports.target_type` and `status`; `verification_log.decision`; `organizations.verification_status`.  
**Planned indexes**  
- B-tree: `users(email)`, `help_requests(author_id)`, `help_requests(claimed_by)`, `help_requests(status)`, `opportunities(organization_id)`, `opportunities(start_time)`, `opportunity_signups(opportunity_id)`, `opportunity_signups(volunteer_id)`, `reports(target_type, target_id, status)`.  
- **PostGIS GiST:** `help_requests.location`, `help_requests.approx_location`, `opportunities.location` — these power the radius search (`ST_DWithin`) and distance sorting (`ST_Distance`).  
**ER / database diagram**  
See [`docs/database-design.puml` — render with any PlantUML viewer (e.g. the PlantUML VS Code extension, or `plantuml docs/database-design.puml`).](./docs/database-design.puml "./docs/database-design.puml")  
  
---  
**2. UX / UI**  
A first version of the main screens and user flows is implemented as a real **HTML + Leaflet** frontend (it is the actual working client). The frontend is served by the FastAPI backend at `/`.  
**Main screens**  
  
|  |  |  |  
| - | - | - |  
| **Screen** |  **File** |  **Purpose** |  
| **Map (home)** |  [`frontend/index.html`](./frontend/index.html "./frontend/index.html") |  Interactive Leaflet map; radius + category search; markers for open requests; click a marker → detail panel with role-aware actions (claim, complete, confirm, cancel, reopen, release). |  
| **Login** |  [`frontend/login.html`](./frontend/login.html "./frontend/login.html") |  Email + password → JWT stored in `localStorage`. |  
| **Register** |  [`frontend/register.html`](./frontend/register.html "./frontend/register.html") |  Choose roles (Resident / Volunteer / Organization, combinable); explains that Moderator cannot be self-chosen. |  
| **Create request** |  [`frontend/create.html`](./frontend/create.html "./frontend/create.html") |  Pick a point on a Leaflet map, choose category, describe the need, optional exact address; shows the privacy notice. |  
  
   
**User flows**  
- **Resident flow:** register (Resident) → create request (pick point on map) → see it on the map → after a volunteer completes it, **Confirm received**.  
- **Volunteer flow:** register (Volunteer) → open map → search by radius/category → click marker → **Claim** (exact address revealed) → **Mark completed**.  
- **Privacy flow:** the detail panel explicitly shows whether the location is *exact* or *approximate* and hides the address until the viewer is the author or the claimer.  
Styling: [`frontend/css/style.css`. Shared client logic:](./frontend/css/style.css "./frontend/css/style.css") [`frontend/js/app.js`.](./frontend/js/app.js "./frontend/js/app.js")  

### Frontend architecture note (not production-grade)

The Alpha frontend is a **plain static frontend**: HTML pages plus a single shared `js/app.js` file, with Leaflet loaded from a CDN. There is no framework, no build step, no bundler, and no `npm`/Node.js toolchain — FastAPI just serves the `frontend/` directory as static files, so the whole prototype runs from one `uvicorn` process.

`app.js` is a single file because the prototype has only four pages and a handful of cross-cutting concerns (a `fetch` wrapper with auth-token injection, login/logout helpers, and small UI utilities). Each HTML page inlines its own page-specific logic in a `<script>` block, and `app.js` holds the few functions every page needs. This is a deliberate shortcut for a runnable Alpha, **not an architecture to keep**: the shared file conflates concerns (API client, auth state, UI rendering, constants) that should be separate modules, and rendering is done by mutating `innerHTML` strings rather than by a component model. It is good enough to prove the end-to-end scenario and the API, but it would not scale to the full product.

**How this will be fixed (Stage 2):** the static frontend will be replaced with a proper component-based frontend project (e.g. Next.js/React or a structured Vite project) that talks to the same FastAPI JSON API.

---  
**3. Working prototype**  
**Initial FastAPI backend —** [`backend/`](./backend/ "./backend/")  
- `app/main.py` — FastAPI app, CORS, startup schema init, serves the frontend.  
- `app/routers/auth.py` — `POST /auth/register`, `POST /auth/login` (JWT), `GET /auth/me`.  
- `app/routers/requests.py` — full help-request lifecycle + PostGIS map search + privacy filtering.  
- `app/security.py` (bcrypt hashing + JWT), `app/deps.py` (JWT dependency + role guard), `app/geo.py` (approx-location rounding), `app/seed.py` (first moderator), `app/models.py` / `app/schemas.py`.  
**Connection to PostgreSQL**  
- Real PostgreSQL + **PostGIS** via `psycopg2` + SQLAlchemy + GeoAlchemy2. No in-memory substitute.  
- `docker-compose.yml` runs `postgis/postgis:16-3.4`; `db/init.sql` is applied on startup and by the container entrypoint.  
**Part of the planned data model implemented**  
- **Fully implemented & exercised:** `users`, `help_requests` (with PostGIS geography columns, indexes, and the state-machine CHECK constraint).  
- **Created (schema present, API out of Alpha scope):** `organizations`, `opportunities`, `opportunity_signups`, `reports`, `verification_log`. These exist so the design is complete and consistent; their endpoints are Stage 3 work.  
**Partial backend functionality**  
- Auth: register (role selection), login (JWT), `me`, blocked-user token rejection.  
- Requests: create (with active-limit ≤ 3), map search (PostGIS `ST_DWithin` + `ST_Distance`, category filter), get detail (privacy-filtered), claim (atomic, concurrency-safe, self-claim & active-claim ≤ 2 rejected), release, complete, confirm, reopen, cancel — all through the allowed state-machine transitions only.  
**Partial frontend functionality**  
- All four main screens work against the live API; the map shows approximate markers and the detail panel adapts actions to the viewer's role and the request's status.  
**End-to-end scenario (screen → backend → database → back)**  
**Flow:** register resident → login → resident creates a request with a location → volunteer registers/logs in → volunteer searches the map (sees approximate location, no address) → volunteer views detail (address hidden) → volunteer claims (atomic UPDATE, exact address now revealed) → volunteer marks completed → resident confirms.  
  
---  
**4. Responsibilities & contributions so far**  
  
|  |  |  |  
| - | - | - |  
| **Member** |  **Owns** |  **Contributed in this Alpha** |  
| **Uliana Matviienko** |  Code (backend + frontend) |  Wrote all the code for this Alpha: the FastAPI backend (auth, JWT, role-based authorization, the help-request lifecycle, claim/release with concurrency safety, active-request & claim limits, self-claim rejection, exact-vs-approximate privacy rules, PostGIS radius search), the SQLAlchemy/GeoAlchemy2 ORM models, the moderator seed script, the bcrypt password hashing, the HTML + Leaflet frontend (map, login, register, create-request, detail panel), the API↔frontend wiring, and the end-to-end testing. |  
| **Bogdan Borachuk** |  Database architecture |  Designed the entire database architecture: the PostgreSQL + PostGIS schema (`db/init.sql`), all entities and their attributes, relationships and cardinalities, primary/foreign keys, constraints (uniqueness, not-null, CHECK), and the planned B-tree and PostGIS GiST indexes. Also produced the ER diagram and the architecture/flow PlantUML diagrams. |  
| Both |  Design (collaboration) |  Discussed and agreed on the system design together — the data model, the request lifecycle state machine, the privacy-by-role rules, the API contract, and the end-to-end scenario — before and during implementation. |  
  
   
  
---  
**5. Note on changes to Stage 1 requirements**  
No functional requirements from the Stage 1 proposal were dropped. The following are **scoped to later stages**, with reasons:  
  
|  |  |  
| - | - |  
| **Item** |  **Reason for deferral** |  
| Organization verification workflow, opportunities, sign-ups, attendance, org/moderator statistics |  Schema is designed and created; the Alpha focuses on proving the core request lifecycle + PostGIS + privacy, so the organization API is Stage 3. |  
| Reports, the 3-reports-auto-hide rule, moderator block/review |  Tables designed and created; trust/moderation endpoints are Stage 3. |  
| Real-time chat, push notifications, mobile apps |  Explicitly out of scope per the Stage 1 proposal. |  
  
   
**Technical note (no requirement change):** password hashing uses the `bcrypt` library directly instead of `passlib`, because `passlib 1.7.4` is incompatible with `bcrypt ≥ 4.1` (a known upstream bug). The behaviour (salted bcrypt hashes) is identical to what the proposal implies.  
  
---  
**6. How to run**  
```  
# 1. Database (PostgreSQL + PostGIS)  
 docker compose up -d db  
   
 # 2. Backend (also serves the frontend)  
 cd backend  
 python -m venv .venv && source .venv/bin/activate  
 pip install -r requirements.txt  
 export DATABASE_URL="postgresql+psycopg2://razom:razom@localhost:5432/razom"  
 export JWT_SECRET="dev-secret-change-me"  
 uvicorn app.main:app --reload --port 8000  
   
 # 3. (optional) first moderator  
 python -m app.seed --email admin@razom.app --password admin123  
   
```  
Open **http://localhost:8000/**  
  
---  
**7. Open risks**  
1. **Auth state in `localStorage`** — JWT in `localStorage` is vulnerable to XSS. Stage 3 should move to `HttpOnly` cookies + CSRF protection.  
2. **No automated test suite yet** — the scenario is validated manually/with scripts; Stage 3 adds `pytest` coverage of the state machine and concurrency rules.  
3. **No migrations tool yet** — schema is applied via `init.sql`; Stage 3 will introduce Alembic for versioned migrations (the DB design already matches the model).  
4. **Moderation & organization APIs not implemented** — the trust model (verification, reports, auto-hide, blocking) is designed but not yet wired to endpoints.  
5. **Frontend is a single-file static prototype** — all client logic lives in one `frontend/js/app.js` with no framework, no build step, and `innerHTML`-based rendering. This is fine to prove the Alpha scenario but is **not production-grade**; it conflates API client, auth, and UI concerns in one file and would not scale. Stage 2 replaces it with a component-based frontend (Next.js/React or Vite) talking to the same JSON API — see the "Frontend architecture note" in section 2.  
  
---  
**Completion-criteria checklist**  
- Database design is complete and consistent with Stage 1 requirements.  
- The prototype runs, is connected to PostgreSQL (+ PostGIS), and implements part of the data model.  
- At least one scenario works from screen to database and back (register → create → claim → complete → confirm).  
- The UX/UI covers the main screens and flows (map, login, register, create-request, detail).  
- The planned architecture is viable; open risks are named above.  
- Map search returns markers at the **approximate** point (\~154 m offset from the exact point) sorted by distance, with **no address**.  
- After claim, the volunteer receives the **exact** coordinates and the address; `claimed_by` is set.  
- Lifecycle completes `open → claimed → completed → confirmed`.  
- Rule checks: concurrent claims → exactly one `200` and one `409`; self-claim and non-resident creation rejected; invalid transitions `409`; missing token `401`.  
