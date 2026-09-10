from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pool_machines DROP COLUMN IF EXISTS profile")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE pool_machines ADD COLUMN IF NOT EXISTS profile VARCHAR(16) "
        "NOT NULL DEFAULT 'full'",
    )
