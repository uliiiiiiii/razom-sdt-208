# Razom — Beta Version Report (Stage 3)

**Project:** Razom, a mutual-aid map connecting residents who need help with volunteers and verified organizations
**Team:** Uliana Matviienko, Bogdan Borachuk
**Stack:** FastAPI · PostgreSQL 16 + PostGIS · Alembic · JWT · Vite · Leaflet

---

## 1. What changed since the Alpha

- **All four roles work end to end through the API.** Before, only residents and volunteers had endpoints. Organizations and moderators now have the API they need: verification, opportunities, sign-ups, attendance, reports, moderation and statistics.
- **Stronger protection for vulnerable residents.** A volunteer sees the exact address only after the resident has accepted them, and only while the help is in progress. Every time someone other than the resident sees an address, it's logged, and addresses are deleted 30 days after a request is closed. Claiming is limited, and an unaccepted claim expires after 12 hours.
- **Schema under version control.** The schema is now managed with Alembic migrations, and all routes are under `/api`.
- **A new frontend.** The Alpha HTML pages are replaced by a Vite app: log in, register, the map, and creating a request. See section 6.

## 2. Requirements status

| # | Requirement (Stage 1) | Note |
|---|---|---|
| 1 | Register as Resident / Volunteer / Organization (R+V combinable) | Organization accounts must give a name |
| 2 | Login → JWT; 401 without a valid token | Token valid 24 h; blocked accounts get 401 "Account is blocked" |
| 3 | Role restrictions → 403 | Roles read from the DB on every request |
| 4 | Organization can't publish until approved | |
| 5 | Moderator not self-registered; seed script; promotion | `python -m app.seed`, `PATCH /api/moderation/users/{id}` |
| 6 | Resident creates a request (category, description, location) | |
| 7 | Status lifecycle, other transitions rejected | **Changed:** the resident must accept or decline the volunteer before help starts |
| 8 | Claim; second claim and self-claim rejected | Concurrency-safe (atomic UPDATE + row locks) |
| 9 | Volunteer releases → open | |
| 10 | Max 2 claimed requests per volunteer | **Added:** max 5 claims per 24 h; unaccepted claims expire after 12 h |
| 11 | Only the claimer completes | Only after the resident accepted them |
| 12 | Resident confirms, or "not resolved" → open | |
| 13 | Resident cancels while open/claimed | |
| 14 | Max 3 active requests per resident | |
| 15 | Public map shows approximate location only | ~300 m grid; never an address |
| 16 | Exact address only for author, current claimer, moderator via open report | **Changed:** claimer only after acceptance and only while `claimed`; every reveal is logged |
| 17 | Verified organization creates / edits / closes opportunities | |
| 18 | Sign up only with free slots and before the start | Row lock prevents overbooking |
| 19 | No double sign-up; cancelling frees the slot | |
| 20 | Attendance after the start, kept in the volunteer's history | |
| 21 | Radius search for requests and opportunities, sorted by distance | PostGIS `ST_DWithin` / `ST_Distance` |
| 22 | Filter by category and type | |
| 23 | Map markers; clicking one shows the details the role may see | Markers at the approximate position; details follow the FR 16 rules |
| 24 | Any user reports a request, opportunity or user | |
| 25 | Moderator dismisses, hides, blocks; blocked users can't log in, old tokens rejected | Blocking also returns the volunteer's claims to the map |
| 26 | 3 reports → item hidden / user suspended until review | **Changed:** moderators are never auto-suspended; "dismiss" undoes only automatic hides |
| 27 | Moderator approves / rejects organizations with a comment | History in `verification_log` |
| 28 | Organization statistics | |
| 29 | Moderator platform statistics and any organization's statistics | |

No requirement was dropped. Explicitly out of scope (as in Stage 1): chat, push notifications, mobile apps, volunteer identity verification.

## 3. Data model

The full model is implemented, and the **updated ER diagram** is in [`docs/ER.md`](./docs/ER.md). Since the Alpha:
- **New tables:** `claim_history` and `address_access_log`.
- **New columns:** acceptance, closing and hiding on requests; categories on opportunities.
- **Removed:** the unused `phone` field.

Relationships, UNIQUE and CHECK constraints, and B-tree and GiST indexes are real migrations, not only on the diagram. The table in `docs/ER.md` shows which constraint enforces which rule.

## 4. Authentication and authorization

- **Authentication:**
  - Passwords are stored as bcrypt hashes, with a minimum of 8 characters.
  - Login returns an HS256 JWT valid for 24 h; tokens without an expiry are rejected.
  - The server refuses to start without a strong `JWT_SECRET`.
  - Login and registration are rate-limited.
- **Authorization:** enforced only by the backend. Each route declares its roles (`require_roles(...)`), and ownership is checked on every `{id}` route: 403 means "not your role or not yours"; 404 means "doesn't exist, or you may not know it exists".

| Role | Can do |
|---|---|
| Resident | Create, cancel, accept or decline the volunteer, confirm requests; see own requests with exact data |
| Volunteer | Search the map, claim / release / complete requests, sign up for opportunities, see own history |
| Organization | After approval: publish and manage opportunities, see sign-ups, mark attendance, view statistics |
| Moderator | Handle reports, hide content, block or promote users, verify organizations, view statistics and the address access log |

Any logged-in user can report content or another user.

## 5. Problems found during the Alpha and how they were resolved

| # | Problem | Resolution |
|---|---|---|
| 1 | The DB container crashed because the init script path was wrong | Fixed the path; the schema is now created by Alembic on startup |
| 2 | The Claim button returned 405 (frontend PATCH vs backend POST) | All state transitions use PATCH |
| 3 | The "Search" button never worked (listener after `</html>`) | Fixed; the new frontend replaces the page |
| 4 | Stored XSS: user text was inserted with `innerHTML` | Text is escaped; React escapes by default; added a Content-Security-Policy |
| 5 | Wrong state transitions were possible (kick a volunteer, reopen a completed request) | Transitions are allowed per action, not just per state |
| 6 | Moderators saw every exact address | Only through an open report, and logged |
| 7 | Parallel requests bypassed the active-request and claim limits | User and request rows are locked before checking a limit |
| 8 | An unknown category gave 500; blank descriptions were accepted | Validated input (422) with length limits |
| 9 | Emails were case-sensitive (duplicate accounts) | Emails are lowercased |
| 10 | Alpha risk: JWT in `localStorage` could be stolen through XSS | Escaping + CSP + security headers; HttpOnly cookies remain future work |
| 11 | Alpha risk: no automated tests | 133 pytest tests against a real PostGIS database |
| 12 | Alpha risk: no migrations | Alembic (3 migrations); existing Alpha databases upgrade cleanly |
| 13 | Alpha risk: moderation and organization APIs missing | Implemented (FR 4, 5, 17–20, 24–29) |
| 14 | Alpha risk: single-file static frontend | Replaced by the Vite app in `frontend/` (section 6), built against `docs/FRONTEND-API.md` |

A security review of the Beta backend found further issues before the frontend work began. All of them are fixed and covered by tests, for example accepting a different volunteer from a stale page, claim squatting, and fake reports locking out moderators.

## 6. Frontend

The Alpha pages are replaced by a Vite app in `frontend/src`. It is plain JavaScript modules, not React. A hash router (`#/`, `#/login`, `#/register`, `#/create`) draws each screen into the page. The contract it follows is [`docs/FRONTEND-API.md`](./docs/FRONTEND-API.md).

| Screen | What it does |
|---|---|
| Log in / Register | Register as resident, volunteer, or organization (resident and volunteer can be combined). An organization must give a name. The JWT is kept in `localStorage` and sent as `Authorization: Bearer`. |
| Map | Search within a radius (up to 50 km), and filter by category and by needs or offers. A request is a colored circle with its category icon; an offer is a ring. Pins posted in the last 6 hours pulse. The list is ordered by urgency (medicine, water, groceries, charging, pets, transport, other), then newest first. Opening a request shows only the actions that role may take: claim, accept or decline, complete, release, confirm, reopen, cancel. |
| Ask for help | The resident drops a pin and sends a category, title, description, and address. The public pin stays about 300 m from that point. |

The page has a light theme and a dark theme meant for a room during a blackout. Fonts (Outfit, Manrope) and icons (Lucide, bundled) are part of the build, so nothing is loaded from a CDN. Map tiles are OpenStreetMap. User text is escaped before it is inserted into the page.

`npm run build` writes `frontend/dist`. FastAPI serves that folder at `/`, and the content security policy allows fetches only from the same origin, so the app always calls `/api`. During development, Vite proxies `/api` to `http://localhost:8000`.

Not in the interface yet: publishing opportunities, filing reports, and the moderator tools. Those exist on the API only.

## 7. Contributions (Beta)

| Member | Contribution |
|---|---|
| **Bogdan Borachuk** | Accounts, security, moderation and organizations: registration, login and JWT, role-based authorization, moderator seeding and promotion, organization verification, reports and the 3-report auto-hide rule, blocking (with rejection of old tokens), opportunities with slot and start-time rules, attendance, organization and moderator statistics, rate limits and security headers; login and registration in the frontend, and the tests |
| **Uliana Matviienko** | Help requests, privacy and the map: PostgreSQL schema and Alembic migrations, the request lifecycle and allowed transitions, claim / release / accept with concurrency safety, active-request and claim limits, exact vs approximate location rules, the address access log and retention, PostGIS radius search and filters, the Leaflet map; the map and “ask for help” screens, and the tests |

Both members took part in integrating the frontend with the API and in fixing the problems found during the Alpha.

## 8. How to run

```bash
docker compose up -d db                          # PostGIS on port 5433
cd backend && pip install -r requirements.txt
export JWT_SECRET="<random string, at least 32 characters>"
uvicorn app.main:app --port 8000                 # migrates the DB on start
python -m app.demo_seed                          # demo accounts for every role (dev only)
pytest                                           # after: pip install -r requirements-dev.txt

cd ../frontend && npm install                    # back to the repo, then frontend/
npm run dev                                      # http://127.0.0.1:5173 , proxies /api to port 8000
npm run build                                    # frontend/dist, then open http://localhost:8000
```

API reference: http://localhost:8000/docs · Frontend guide: [`docs/FRONTEND-API.md`](./docs/FRONTEND-API.md)
