from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS opal_sessions (
            id SERIAL PRIMARY KEY,
            refresh_token VARCHAR(128) NOT NULL UNIQUE,
            label VARCHAR(64),
            enabled BOOLEAN NOT NULL DEFAULT true,
            failures INTEGER NOT NULL DEFAULT 0,
            cooldown_until TIMESTAMPTZ,
            last_error TEXT,
            last_used_at TIMESTAMPTZ,
            uses INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE turns DROP CONSTRAINT IF EXISTS turns_credential_id_fkey")
    op.execute("UPDATE turns SET credential_id = NULL WHERE credential_id IS NOT NULL")
    op.execute("DROP TABLE IF EXISTS anthropic_credentials")
    op.execute("""
        ALTER TABLE turns
        ADD CONSTRAINT turns_credential_id_fkey
        FOREIGN KEY (credential_id) REFERENCES opal_sessions(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE turns DROP CONSTRAINT IF EXISTS turns_credential_id_fkey")
    op.execute("UPDATE turns SET credential_id = NULL WHERE credential_id IS NOT NULL")
    op.execute("DROP TABLE IF EXISTS opal_sessions")
    op.execute("""
        CREATE TABLE IF NOT EXISTS anthropic_credentials (
            id SERIAL PRIMARY KEY,
            kind VARCHAR(8) NOT NULL,
            secret TEXT NOT NULL UNIQUE,
            label VARCHAR(64),
            enabled BOOLEAN NOT NULL DEFAULT true,
            failures INTEGER NOT NULL DEFAULT 0,
            cooldown_until TIMESTAMPTZ,
            last_error TEXT,
            last_used_at TIMESTAMPTZ,
            uses INTEGER NOT NULL DEFAULT 0,
            total_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        ALTER TABLE turns
        ADD CONSTRAINT turns_credential_id_fkey
        FOREIGN KEY (credential_id) REFERENCES anthropic_credentials(id) ON DELETE SET NULL
    """)
