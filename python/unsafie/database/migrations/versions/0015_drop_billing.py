from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS balance")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS budget")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS cost_usd")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS charge")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS locked")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS config")


def downgrade() -> None:
    pass
