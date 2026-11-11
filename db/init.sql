-- Razom — database schema (PostgreSQL + PostGIS)
-- Stage 2 Alpha: full design; the request-lifecycle tables are exercised
-- end-to-end. Organization/opportunity/report tables are created now so the
-- design is complete and consistent, even though their API is out of scope
-- for this Alpha scenario.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Status / enum-like CHECK constraints are used (portable across PG versions)
-- instead of native enums so future migrations stay simple.

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT        NOT NULL UNIQUE,
    password_hash   TEXT        NOT NULL,
    display_name    TEXT        NOT NULL,
    phone           TEXT,
    is_resident     BOOLEAN     NOT NULL DEFAULT FALSE,
    is_volunteer    BOOLEAN     NOT NULL DEFAULT FALSE,
    is_organization BOOLEAN     NOT NULL DEFAULT FALSE,
    is_moderator    BOOLEAN     NOT NULL DEFAULT FALSE,
    is_blocked      BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- organizations  (1:1 profile for users with is_organization = true)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organizations (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT      NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    org_name            TEXT        NOT NULL,
    description         TEXT,
    verification_status TEXT        NOT NULL DEFAULT 'pending'
                        CHECK (verification_status IN ('pending', 'approved', 'rejected')),
    verified_at         TIMESTAMPTZ,
    verified_by         BIGINT      REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- help_requests  (core of the Alpha scenario)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS help_requests (
    id              BIGSERIAL PRIMARY KEY,
    author_id       BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category        TEXT        NOT NULL
                    CHECK (category IN ('charging','groceries','medicine','water','transport','pets','other')),
    title           TEXT,
    description     TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','claimed','completed','confirmed','cancelled')),
    -- exact location (author + claimer + moderator-on-report only)
    location        geography(POINT, 4326) NOT NULL,
    -- approximate, publicly visible location (rounded ~300m)
    approx_location geography(POINT, 4326),
    address         TEXT,
    claimed_by      BIGINT      REFERENCES users(id),
    claimed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- a 'claimed' request must have a claimer (completed/confirmed keep the claimer)
    CONSTRAINT chk_claim_consistency
        CHECK ( status <> 'claimed' OR claimed_by IS NOT NULL )
);

-- ---------------------------------------------------------------------------
-- opportunities  (organizations)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS opportunities (
    id              BIGSERIAL PRIMARY KEY,
    organization_id BIGINT      NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title           TEXT        NOT NULL,
    description     TEXT,
    location        geography(POINT, 4326) NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    slots_total     INTEGER     NOT NULL CHECK (slots_total > 0),
    status          TEXT        NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','closed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- opportunity_signups  (volunteer <-> opportunity, many-to-many with slots)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS opportunity_signups (
    id              BIGSERIAL PRIMARY KEY,
    opportunity_id  BIGINT      NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    volunteer_id    BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signed_up_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    attended        BOOLEAN,
    CONSTRAINT uniq_signup UNIQUE (opportunity_id, volunteer_id)
);

-- ---------------------------------------------------------------------------
-- reports  (trust & moderation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    id              BIGSERIAL PRIMARY KEY,
    reporter_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type     TEXT        NOT NULL CHECK (target_type IN ('request','opportunity','user')),
    target_id       BIGINT      NOT NULL,
    reason          TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','dismissed','actioned')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uniq_report UNIQUE (reporter_id, target_type, target_id)
);

-- ---------------------------------------------------------------------------
-- verification_log  (moderator decision history for organizations)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verification_log (
    id              BIGSERIAL PRIMARY KEY,
    organization_id BIGINT      NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    moderator_id    BIGINT      NOT NULL REFERENCES users(id),
    decision        TEXT        NOT NULL CHECK (decision IN ('approved','rejected')),
    comment         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_users_email            ON users (email);
CREATE INDEX IF NOT EXISTS idx_requests_author        ON help_requests (author_id);
CREATE INDEX IF NOT EXISTS idx_requests_claimed_by    ON help_requests (claimed_by);
CREATE INDEX IF NOT EXISTS idx_requests_status        ON help_requests (status);
-- PostGIS GIST indexes for radius / distance queries
CREATE INDEX IF NOT EXISTS idx_requests_location      ON help_requests USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_requests_approx_loc    ON help_requests USING GIST (approx_location);
CREATE INDEX IF NOT EXISTS idx_opp_org                ON opportunities (organization_id);
CREATE INDEX IF NOT EXISTS idx_opp_start_time         ON opportunities (start_time);
CREATE INDEX IF NOT EXISTS idx_opp_location           ON opportunities USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_signup_opp             ON opportunity_signups (opportunity_id);
CREATE INDEX IF NOT EXISTS idx_signup_vol             ON opportunity_signups (volunteer_id);
CREATE INDEX IF NOT EXISTS idx_reports_target         ON reports (target_type, target_id, status);

