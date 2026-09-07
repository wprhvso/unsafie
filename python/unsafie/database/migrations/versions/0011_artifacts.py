from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shares")
    op.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id SERIAL PRIMARY KEY,
            slug VARCHAR(12) NOT NULL UNIQUE,
            kind VARCHAR(16) NOT NULL DEFAULT 'markdown',
            title VARCHAR(200),
            content TEXT,
            bot_id INTEGER REFERENCES bots (id) ON DELETE CASCADE,
            chat_id BIGINT,
            turn_id UUID REFERENCES turns (id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artifacts_chat ON artifacts (bot_id, chat_id, created_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_artifacts_turn "
        "ON artifacts (turn_id) WHERE kind = 'turn'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS artifacts")
    op.execute("""
        CREATE TABLE IF NOT EXISTS shares (
            id SERIAL PRIMARY KEY,
            response_id UUID NOT NULL UNIQUE REFERENCES responses (id) ON DELETE CASCADE,
            slug VARCHAR(12) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
