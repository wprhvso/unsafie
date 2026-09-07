from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.execute("CREATE INDEX IF NOT EXISTS ix_transcripts_chat ON transcripts (bot_id, chat_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_transcripts_updated ON transcripts (updated_at)")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS transcript_lines INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS transcript_lines")
    op.execute("DROP TABLE IF EXISTS transcripts")
