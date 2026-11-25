# Razom API — guide for the frontend

Everything the frontend needs from the backend on branch `beta`. The interactive reference with every request/response schema is **http://localhost:8000/docs** (Swagger). Click **Authorize** and paste a token from `POST /api/auth/login` to try protected routes.

## 1. Run the backend locally

```bash
docker compose up -d db                      # PostGIS on localhost:5433
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn app.main:app --reload --port 8000    # creates/updates the schema on start
python -m app.demo_seed                      # demo accounts + content (dev only)
```

Demo accounts (password `demo-pass-123`):

| Email | Role |
|---|---|
| `resident@razom.demo` | Resident (2 open requests) |
| `volunteer@razom.demo` | Volunteer |
| `org@razom.demo` | Organization, approved (2 opportunities) |
| `pending-org@razom.demo` | Organization, waiting for approval |
| `moderator@razom.demo` | Moderator |

## 2. Frontend project setup

- **Location and build output:** put the frontend project in `frontend/` and build into `frontend/dist` (Vite's default). FastAPI then serves `dist/` at `/`. Any unknown path returns `index.html`, so client-side routes like `/requests/5` survive a page refresh. Only `dist/` is ever served, never the sources.
- **Development:** proxy `/api` to the backend; there's no CORS to configure:

  ```js
  // vite.config.js
  export default { server: { proxy: { "/api": "http://localhost:8000" } } }
  ```

- **Content-Security-Policy:** the production page is served with this CSP. The Vite dev server doesn't apply it, so **test the built app** at `http://localhost:8000` before the demo.
  - **Allowed:** scripts, styles and fetches from the same origin only, plus inline styles. Images from the same origin, `data:` URLs, and `https://tile.openstreetmap.org` / `https://*.tile.openstreetmap.org`.
  - **Not allowed:** CDN `<script>`/`<link>` tags (bundle Leaflet and fonts via npm), Google Fonts, inline `<script>`, Leaflet's default marker images from unpkg, and geocoding APIs such as Nominatim. Leaflet's marker PNGs must be imported so Vite bundles them.
- **Escaping:** never render user text with `innerHTML` or `dangerouslySetInnerHTML`. Titles, descriptions, addresses and names are user input.

## 3. Conventions

- **Base URL:** `/api`. All bodies are JSON.
- **Auth:** send `Authorization: Bearer <access_token>`.
  - The token comes from `POST /api/auth/login` and is valid for 24 h.
  - Roles are read from the database on every request. A promoted or blocked user doesn't need a new token, so always take roles from `GET /api/auth/me`, not from the token.
- **Errors** are always `{"detail": ...}`. `detail` is a string, except for 422, where it's FastAPI's list of field errors (`[{loc, msg, ...}]`).

| Status | Meaning | UI |
|---|---|---|
| 400 | Business rule (e.g. reporting yourself) | Show `detail` |
| 401 | No/invalid/expired token → log out. `detail == "Account is blocked"` → explain the account was blocked | Login page |
| 403 | Your role can't do this (or organization not verified yet) | Show `detail` |
| 404 | Doesn't exist **or you're not allowed to know it exists** | "Not found" |
| 409 | State/limit conflict (already claimed, no slots, 3 active requests, volunteer changed, …) | Show `detail`, refresh the item |
| 422 | Invalid input | Show field errors |
| 429 | Too many attempts (login 10/min, register 5/h, new request 10/h, report 20/h) | "Try again later" |

- **Datetimes** in responses are ISO 8601 with timezone. Datetimes you send (`start_time`) **must include an offset**, e.g. `2026-11-20T10:00:00+02:00`, and be in the future. Otherwise the API returns 422.
- **Categories** (requests and opportunities): `charging`, `groceries`, `medicine`, `water`, `transport`, `pets`, `other`. Translate them in the UI.
- **Text limits:**
  - Request: title ≤ 120, description 1–2000, address ≤ 300.
  - Opportunity: title 1–120, description ≤ 2000, slots 1–500.
  - Password ≥ 8, display name 1–100, report reason 3–500.

## 4. Accounts

| Method & path | Who | Body / notes |
|---|---|---|
| `POST /api/auth/register` | anyone | `{email, password, display_name, is_resident, is_volunteer, is_organization, org_name}`. Pick at least one role; resident and volunteer can be combined. `org_name` is required with `is_organization`. Moderator can't be chosen. 409 if the email is taken. |
| `POST /api/auth/login` | anyone | `{email, password}` → `{access_token, user_id, display_name, roles}`. 401 wrong credentials, 403 blocked. |
| `GET /api/auth/me` | logged in | `{id, email, display_name, roles}`. `roles` ⊂ `resident, volunteer, organization, moderator`. |

## 5. Map

`GET /api/map?lat=&lng=&radius=3000&type=all|request|opportunity&category=` (any logged-in user)
→ `[{type, id, category, title, latitude, longitude, distance_m, created_at, detail, start_time, slots_left}]`, sorted by distance. `detail` is one line of the description and never an address. `radius` is in metres, between 1 and 50000. At most the **300 nearest** items come back; exactly 300 means the list was cut, so show "300+" rather than a count.

- **Requests** come back at their **approximate** point, a cell about 300 m wide, never with an address. Draw them as an area or a soft marker, not as a precise pin, and say so in the UI.
- **Opportunities** are at their real location. `start_time` and `slots_left` are set only for opportunities.
- **What the map leaves out:** requests that are claimed, closed or hidden; past, closed or hidden opportunities; and content from blocked users or unapproved organizations. Full opportunities are still shown, with `slots_left = 0`.

## 6. Help requests

### The lifecycle

```
open ──claim (volunteer)──▶ claimed ──accept (resident)──▶ claimed + accepted ──complete (volunteer)──▶ completed
  ▲                           │  │                                                                      │   │
  │◀── decline (resident) ────┘  └── release (volunteer) ──▶ open                       confirm ◀───────┘   └── reopen ──▶ open
  │◀── unaccepted for 12 h (automatic)                                                (resident)  (resident, "not resolved")
open | claimed ──cancel (resident)──▶ cancelled
```

### Endpoints

| Method & path | Who | Notes |
|---|---|---|
| `POST /api/requests` | resident | `{category, description, title?, latitude, longitude, address?}`. 409 at 3 active requests. Returns `RequestOut`. |
| `GET /api/requests/{id}` | logged in | `RequestOut`. 404 for anything that isn't open unless you're its author or volunteer. |
| `PATCH /api/requests/{id}/claim` | volunteer | No body. 409 if it's no longer open, it's your own request, you already hold 2 claims, you made 5 claims in 24 h, or the resident declined you before. |
| `PATCH /api/requests/{id}/accept` | author | **Body `{claim_id}`**, taken from `claimer.claim_id` in the detail you showed. 409 if the volunteer changed meanwhile: reload and show the new volunteer. |
| `PATCH /api/requests/{id}/decline` | author | **Body `{claim_id}`**, same as accept. That volunteer can't claim this request again. |
| `PATCH /api/requests/{id}/release` | claiming volunteer | Back to `open`. |
| `PATCH /api/requests/{id}/complete` | claiming volunteer | Only after the resident accepted. |
| `PATCH /api/requests/{id}/confirm` | author | From `completed`. Closes the request. |
| `PATCH /api/requests/{id}/reopen` | author | "Not resolved": `completed` → `open`. |
| `PATCH /api/requests/{id}/cancel` | author | From `open` or `claimed`. |
| `GET /api/me/requests` | resident | My requests, all statuses, newest first. |
| `GET /api/me/claims` | volunteer | Requests I currently hold or completed. |

### What `RequestOut` contains

| Field | Meaning |
|---|---|
| `id`, `category`, `title`, `description`, `status`, `created_at`, `closed_at` | Basic fields |
| `latitude`, `longitude` | Exact point when `exact_location` is true, otherwise the approximate one |
| `address` | Only when `exact_location` is true |
| `is_mine` | You created it |
| `is_claimer` | You're the current volunteer |
| `accepted` | The resident has accepted the volunteer |
| `is_hidden` | Hidden by a moderator or by 3 reports; tell the owner |
| `claimer` | Only for the author while a volunteer holds it: `{claim_id, display_name, confirmed_count}` |

### Who sees the exact address

- The **author** always sees it.
- The **volunteer** sees it only after the resident accepted them, and only while the status is `claimed`. Once they mark it completed, it's hidden again.
- Every reveal to the volunteer is logged and visible to moderators. The UI should tell volunteers this.

### Which actions to show

| Viewer | Status | Show |
|---|---|---|
| volunteer, not mine | open | Claim |
| author | claimed, `accepted=false` | Volunteer name + `confirmed_count`, Accept / Decline |
| author | open or claimed | Cancel (ask for confirmation) |
| claimer | claimed, `accepted=false` | "Waiting for the resident", Release |
| claimer | claimed, `accepted=true` | Address, Mark completed, Release |
| author | completed | Confirm / Not resolved |
| anyone except author | any | Report |

The backend enforces every rule above; hiding buttons only keeps the UI tidy.

## 7. Organizations and opportunities

| Method & path | Who | Notes |
|---|---|---|
| `GET /api/me/organization` | organization | `{id, org_name, verification_status: pending\|approved\|rejected, comment}`. Show a banner while pending, and the moderator's comment if rejected. |
| `POST /api/opportunities` | approved organization | `{title, category, description?, latitude, longitude, start_time, slots_total}`. 403 until approved. |
| `PATCH /api/opportunities/{id}` | owner | Any subset of the create fields. `null` = unchanged. 409 if slots would drop below sign-ups. |
| `PATCH /api/opportunities/{id}/close` | owner | Stops sign-ups. |
| `GET /api/opportunities/{id}` | logged in | `{id, organization{id, org_name}, title, description, category, latitude, longitude, start_time, slots_total, slots_taken, status, is_signed_up, is_owner, is_hidden}` |
| `GET /api/me/opportunities` | organization | Mine, newest start first. |
| `POST /api/opportunities/{id}/signups` | volunteer | 201 `{id, volunteer, signed_up_at, attended}`. 409: full, closed, started, already signed up. |
| `DELETE /api/opportunities/{id}/signups/me` | volunteer | 204. 409 after the start. |
| `GET /api/opportunities/{id}/signups` | owner | `[{id, volunteer{id, display_name}, signed_up_at, attended}]` |
| `PATCH /api/opportunities/{id}/signups/{signup_id}` | owner | `{attended: true\|false}`, only after `start_time` (409 before). |
| `GET /api/me/signups` | volunteer | `[{id, opportunity{id, title, start_time, status, organization}, signed_up_at, attended}]` |
| `GET /api/me/organization/stats` | organization | `{opportunities_total, opportunities_open, signups_total, attended_total, past_opportunities}` |

## 8. Reports

`POST /api/reports` (any logged-in user) `{target_type: request|opportunity|user, target_id, reason}`
→ 201 `{id, status}`; 400 for reporting yourself or your own content; 404 for an unknown target or one you can't open (hidden, or a request that isn't open and isn't yours); 409 if you already reported it.

Three reports from different users hide the item automatically (or suspend the user, unless they're a moderator) until a moderator decides.

## 9. Moderation (moderator only; everything else gets 403)

| Method & path | Notes |
|---|---|
| `GET /api/moderation/reports?status=open\|dismissed\|actioned` | `[{id, target_type, target_id, reason, status, created_at, reporter{id, display_name}, open_reports_on_target}]` |
| `GET /api/moderation/reports/{id}` | The same fields plus `target`, the reported request/opportunity/user. For a request with an **open** report, `target` includes the exact address, and **this view is logged**. Say so on screen. |
| `PATCH /api/moderation/reports/{id}` | `{decision: dismiss\|hide\|block}`. It resolves all open reports on that target. `dismiss` undoes an automatic hide; `hide` applies to content only; `block` blocks the user or the content's owner. 409 if already resolved. |
| `PATCH /api/moderation/requests/{id}` | `{is_hidden}`: hide or unhide a request directly. |
| `PATCH /api/moderation/opportunities/{id}` | `{is_hidden}` |
| `GET /api/moderation/organizations?status=pending\|approved\|rejected` | `[{id, org_name, verification_status, created_at, user{id, email, display_name, roles}}]` |
| `PATCH /api/moderation/organizations/{id}` | `{decision: approved\|rejected, comment?}` |
| `GET /api/moderation/organizations/{id}/stats` | The same shape as the organization's own stats. |
| `GET /api/moderation/users?q=` | Search by email or name (max 50): `[{id, email, display_name, roles, is_blocked, created_at}]` |
| `PATCH /api/moderation/users/{id}` | `{is_blocked?, is_moderator?}`. Blocking releases their claims. You can't change yourself (400). |
| `GET /api/moderation/access-log?request_id=` | Who saw which exact address, when, and how: `[{request_id, user{id, display_name}, via: claim\|report_review, accessed_at}]` |
| `GET /api/moderation/stats` | `{requests_by_status, requests_by_category, users_total, active_users_30d, pending_reports, pending_organizations}` |

## 10. Not available yet

- Pagination: lists return everything (moderation users: 50, access log: 200).
- Editing a request after creating it.
- Profile or password changes, and logout on the server. Logging out means deleting the token in the browser.
- Machine-readable error codes. `detail` is English; map the common ones in the UI.
