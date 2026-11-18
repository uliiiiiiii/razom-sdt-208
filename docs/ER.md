# Razom — ER diagram (Beta)

Schema as created by the Alembic migrations in `backend/app/migrations/versions/` (0001 baseline, 0002 Beta, 0003 review fixes). PostgreSQL 16 + PostGIS; `geography(Point, 4326)` columns have GiST indexes.

Image version: [`ER.png`](./ER.png) (rendered from the diagram below).

```mermaid
erDiagram
    users ||--o| organizations : "has profile (is_organization)"
    users ||--o{ help_requests : "author_id"
    users |o--o{ help_requests : "claimed_by"
    organizations ||--o{ opportunities : "publishes"
    opportunities ||--o{ opportunity_signups : "has"
    users ||--o{ opportunity_signups : "volunteer_id"
    users ||--o{ reports : "reporter_id"
    organizations ||--o{ verification_log : "decisions"
    users ||--o{ verification_log : "moderator_id"
    help_requests ||--o{ claim_history : "claims"
    users ||--o{ claim_history : "volunteer_id"
    help_requests ||--o{ address_access_log : "reveals"
    users ||--o{ address_access_log : "viewer"

    users {
        bigint id PK
        text email UK
        text password_hash "bcrypt"
        text display_name
        bool is_resident
        bool is_volunteer
        bool is_organization
        bool is_moderator "seed script / promoted only"
        bool is_blocked
        bool auto_blocked "set by the 3-reports rule"
        timestamptz created_at
    }
    organizations {
        bigint id PK
        bigint user_id FK,UK
        text org_name
        text description
        text verification_status "pending | approved | rejected"
        timestamptz verified_at
        bigint verified_by FK
        timestamptz created_at
    }
    help_requests {
        bigint id PK
        bigint author_id FK
        text category "CHECK: 7 categories"
        text title
        text description
        text status "CHECK: open | claimed | completed | confirmed | cancelled"
        geography location "exact; author, accepted volunteer"
        geography approx_location "~300 m grid; public"
        text address "author, accepted volunteer"
        bigint claimed_by FK
        timestamptz claimed_at
        timestamptz accepted_at "resident accepted the volunteer"
        timestamptz closed_at "drives 30-day address purge"
        bool is_hidden
        bool auto_hidden
        timestamptz created_at
        timestamptz updated_at
    }
    opportunities {
        bigint id PK
        bigint organization_id FK
        text title
        text description
        text category "CHECK: 7 categories"
        geography location
        timestamptz start_time
        int slots_total "CHECK > 0"
        text status "CHECK: open | closed"
        bool is_hidden
        bool auto_hidden
        timestamptz created_at
    }
    opportunity_signups {
        bigint id PK
        bigint opportunity_id FK
        bigint volunteer_id FK
        timestamptz signed_up_at
        bool attended
    }
    reports {
        bigint id PK
        bigint reporter_id FK
        text target_type "CHECK: request | opportunity | user"
        bigint target_id "polymorphic, no FK"
        text reason
        text status "CHECK: open | dismissed | actioned"
        timestamptz created_at
    }
    verification_log {
        bigint id PK
        bigint organization_id FK
        bigint moderator_id FK
        text decision "CHECK: approved | rejected"
        text comment
        timestamptz created_at
    }
    claim_history {
        bigint id PK
        bigint request_id FK
        bigint volunteer_id FK
        timestamptz claimed_at
        text outcome "CHECK: active | released | declined | cancelled | reopened | completed"
    }
    address_access_log {
        bigint id PK
        bigint request_id FK
        bigint user_id FK
        timestamptz accessed_at
        text via "CHECK: claim | report_review"
    }
```

## Constraints and indexes that enforce rules

| Rule | Enforced by |
|---|---|
| One account per email | `users.email` UNIQUE (lowercased by the API) |
| One profile per organization account | `organizations.user_id` UNIQUE |
| No double sign-up | UNIQUE `(opportunity_id, volunteer_id)` |
| One report per user per target | UNIQUE `(reporter_id, target_type, target_id)` |
| Claimed/completed request has a volunteer | `chk_claim_consistency` |
| Only a claimed request can be accepted | `chk_accept_needs_claimer` |
| Valid statuses, categories, decisions | CHECK constraints listed above |
| Fast radius search | GiST on `help_requests.location`, `approx_location`, `opportunities.location` |
| Fast limits and lists | B-tree on `help_requests(author_id)`, `(claimed_by)`, `(status) WHERE NOT is_hidden`, `claim_history(volunteer_id, claimed_at)`, `address_access_log(request_id, accessed_at)`, `reports(target_type, target_id, status)`, `opportunities(start_time) WHERE NOT is_hidden` |

**Changes since the Alpha:**
- New tables `claim_history` and `address_access_log`.
- `help_requests` gains `accepted_at`, `closed_at`, `is_hidden` and `auto_hidden`.
- `opportunities` gains `category`, `is_hidden` and `auto_hidden`.
- `users` gains `auto_blocked`; `users.phone` was removed because it was collected but never used.
