from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transcripts")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS root_id UUID")
    op.execute("UPDATE turns SET parent_id = NULL WHERE parent_id IS NOT NULL")
    op.execute("UPDATE turns SET root_id = id WHERE root_id IS NULL")
    op.execute("ALTER TABLE turns ALTER COLUMN root_id SET NOT NULL")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS session_id")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS forked")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS transcript_lines")
    op.execute("DROP INDEX IF EXISTS ix_turns_session")
    op.execute("CREATE INDEX IF NOT EXISTS ix_turns_root ON turns (root_id, created_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS turn_messages (
            turn_id UUID PRIMARY KEY REFERENCES turns (id) ON DELETE CASCADE,
            count INTEGER NOT NULL DEFAULT 0,
            bytes INTEGER NOT NULL DEFAULT 0,
            body BYTEA NOT NULL,
            system TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("UPDATE turns SET heartbeat_at = NULL WHERE status <> 'running'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS turn_messages")
    op.execute("DROP INDEX IF EXISTS ix_turns_root")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS root_id")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS session_id VARCHAR(36)")
    op.execute(
        "ALTER TABLE turns ADD COLUMN IF NOT EXISTS forked BOOLEAN NOT NULL DEFAULT false",
    )
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS transcript_lines INTEGER")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_turns_session "
        "ON turns (bot_id, chat_id, session_id, created_at)",
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            session_id VARCHAR(64) PRIMARY KEY,
            bot_id INTEGER NOT NULL REFERENCES bots (id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            lines INTEGER NOT NULL DEFAULT 0,
            raw_bytes INTEGER NOT NULL DEFAULT 0,
            body BYTEA NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
