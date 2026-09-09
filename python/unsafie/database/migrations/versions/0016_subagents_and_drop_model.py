from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS model")
    op.add_column(
        "turns",
        sa.Column("is_subagent", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "turns",
        sa.Column("title", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("turns", "title")
    op.drop_column("turns", "is_subagent")
    op.add_column(
        "users",
        sa.Column("model", sa.String(length=64), nullable=True),
    )
