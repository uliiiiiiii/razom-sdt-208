"""Moderator-checked identity verification: submissions, encrypted images,
access log, and the badge/preference columns.

Revision ID: 0004
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE identity_verifications (
        id                   BIGSERIAL PRIMARY KEY,
        user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status               TEXT NOT NULL
            CONSTRAINT chk_verification_status_ck CHECK
            (status IN ('started','pending','approved','rejected','expired','revoked')),
        challenge_word       TEXT NOT NULL,
        challenge_expires_at TIMESTAMPTZ NOT NULL,
        document_fingerprint TEXT,
        submitted_at         TIMESTAMPTZ,
        decided_at           TIMESTAMPTZ,
        decided_by           BIGINT REFERENCES users(id),
        comment              TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX uniq_open_verification ON identity_verifications (user_id)
        WHERE status IN ('started','pending');
    CREATE INDEX ix_verification_fingerprint ON identity_verifications (document_fingerprint);

    CREATE TABLE verification_images (
        id              BIGSERIAL PRIMARY KEY,
        verification_id BIGINT NOT NULL REFERENCES identity_verifications(id) ON DELETE CASCADE,
        kind            TEXT NOT NULL
            CONSTRAINT chk_verification_image_kind_ck CHECK
            (kind IN ('id_document','selfie','profile')),
        data            BYTEA NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uniq_verification_image UNIQUE (verification_id, kind)
    );

    CREATE TABLE verification_access_log (
        id              BIGSERIAL PRIMARY KEY,
        verification_id BIGINT NOT NULL REFERENCES identity_verifications(id) ON DELETE CASCADE,
        moderator_id    BIGINT NOT NULL REFERENCES users(id),
        kind            TEXT NOT NULL,
        accessed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    ALTER TABLE users
        ADD COLUMN is_verified              BOOLEAN NOT NULL DEFAULT false,
        ADD COLUMN verified_at              TIMESTAMPTZ,
        ADD COLUMN photo_image_id           BIGINT,
        ADD COLUMN only_verified_residents  BOOLEAN NOT NULL DEFAULT false;
    -- added after the tables exist: users -> images -> verifications -> users
    ALTER TABLE users ADD CONSTRAINT fk_users_photo_image
        FOREIGN KEY (photo_image_id) REFERENCES verification_images(id) ON DELETE SET NULL;

    ALTER TABLE help_requests ADD COLUMN verified_only BOOLEAN NOT NULL DEFAULT false;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE help_requests DROP COLUMN verified_only;
    ALTER TABLE users DROP CONSTRAINT fk_users_photo_image;
    ALTER TABLE users
        DROP COLUMN only_verified_residents,
        DROP COLUMN photo_image_id,
        DROP COLUMN verified_at,
        DROP COLUMN is_verified;
    DROP TABLE verification_access_log;
    DROP TABLE verification_images;
    DROP TABLE identity_verifications;
    """)
