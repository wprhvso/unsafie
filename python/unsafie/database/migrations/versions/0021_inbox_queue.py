from collections.abc import Sequence
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("ALTER TABLE updates ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'pending'")
    op.execute("ALTER TABLE updates ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ")
    op.execute("UPDATE updates SET status = 'done' WHERE status = 'pending'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_updates_pending ON updates (id ASC) WHERE status = 'pending'")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_updates_pending")
    op.execute("ALTER TABLE updates DROP COLUMN IF EXISTS processed_at")
    op.execute("ALTER TABLE updates DROP COLUMN IF EXISTS status")
