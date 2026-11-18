"""Track automatic hides/blocks separately from moderator decisions, and
backfill closed_at for requests closed before the Beta (so retention purges them).

Revision ID: 0003
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- set by the 3-reports rule; a moderator's dismiss only undoes these
    ALTER TABLE help_requests ADD COLUMN auto_hidden  BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE opportunities ADD COLUMN auto_hidden  BOOLEAN NOT NULL DEFAULT false;
    ALTER TABLE users         ADD COLUMN auto_blocked BOOLEAN NOT NULL DEFAULT false;

    UPDATE help_requests SET closed_at = updated_at
     WHERE status IN ('confirmed', 'cancelled') AND closed_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE users DROP COLUMN auto_blocked;
    ALTER TABLE opportunities DROP COLUMN auto_hidden;
    ALTER TABLE help_requests DROP COLUMN auto_hidden;
    """)
