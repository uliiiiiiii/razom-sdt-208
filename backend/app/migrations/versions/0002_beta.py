"""Beta schema: resident acceptance, claim history, address access log,
content hiding, opportunity categories; drop the unused phone column.

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CATEGORIES = "('charging','groceries','medicine','water','transport','pets','other')"


def upgrade() -> None:
    op.execute(f"""
    -- help_requests: the resident must accept a volunteer before the address
    -- is revealed; closed_at drives address retention; is_hidden is set by
    -- moderators or the 3-reports rule.
    ALTER TABLE help_requests
        ADD COLUMN accepted_at TIMESTAMPTZ,
        ADD COLUMN closed_at   TIMESTAMPTZ,
        ADD COLUMN is_hidden   BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE help_requests DROP CONSTRAINT chk_claim_consistency;
    ALTER TABLE help_requests
        ADD CONSTRAINT chk_claim_consistency
            CHECK (status NOT IN ('claimed','completed') OR claimed_by IS NOT NULL),
        ADD CONSTRAINT chk_accept_needs_claimer
            CHECK (accepted_at IS NULL OR claimed_by IS NOT NULL);
    CREATE INDEX idx_requests_visible_status ON help_requests (status) WHERE is_hidden = false;

    ALTER TABLE opportunities
        ADD COLUMN category  TEXT    NOT NULL DEFAULT 'other',
        ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT false,
        ADD CONSTRAINT chk_opportunity_category CHECK (category IN {CATEGORIES});
    CREATE INDEX idx_opp_visible_start ON opportunities (start_time) WHERE is_hidden = false;

    -- collected but never used: don't keep personal data we don't need
    ALTER TABLE users DROP COLUMN phone;

    -- every claim, including released/declined ones (24h claim limit, re-claim ban)
    CREATE TABLE claim_history (
        id           BIGSERIAL PRIMARY KEY,
        request_id   BIGINT      NOT NULL REFERENCES help_requests(id) ON DELETE CASCADE,
        volunteer_id BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        claimed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        outcome      TEXT        NOT NULL DEFAULT 'active'
                     CHECK (outcome IN ('active','released','declined','cancelled','reopened','completed'))
    );
    CREATE INDEX idx_claim_history_volunteer ON claim_history (volunteer_id, claimed_at);
    CREATE INDEX idx_claim_history_request   ON claim_history (request_id, volunteer_id);

    -- who saw an exact address, when, and through which path
    CREATE TABLE address_access_log (
        id          BIGSERIAL PRIMARY KEY,
        request_id  BIGINT      NOT NULL REFERENCES help_requests(id) ON DELETE CASCADE,
        user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        via         TEXT        NOT NULL CHECK (via IN ('claim','report_review'))
    );
    CREATE INDEX idx_access_log_request ON address_access_log (request_id, accessed_at);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE address_access_log;
    DROP TABLE claim_history;
    ALTER TABLE users ADD COLUMN phone TEXT;
    DROP INDEX idx_opp_visible_start;
    ALTER TABLE opportunities DROP CONSTRAINT chk_opportunity_category,
        DROP COLUMN is_hidden, DROP COLUMN category;
    DROP INDEX idx_requests_visible_status;
    ALTER TABLE help_requests DROP CONSTRAINT chk_accept_needs_claimer,
        DROP CONSTRAINT chk_claim_consistency;
    ALTER TABLE help_requests ADD CONSTRAINT chk_claim_consistency
        CHECK (status <> 'claimed' OR claimed_by IS NOT NULL);
    ALTER TABLE help_requests DROP COLUMN is_hidden, DROP COLUMN closed_at, DROP COLUMN accepted_at;
    """)
