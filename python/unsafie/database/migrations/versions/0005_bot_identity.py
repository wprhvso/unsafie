from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS tg_id BIGINT")
    op.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS username VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS username")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS tg_id")
