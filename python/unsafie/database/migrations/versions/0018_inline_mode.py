from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turns",
        sa.Column("is_inline", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "turns",
        sa.Column("inline_message_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("turns", "inline_message_id")
    op.drop_column("turns", "is_inline")
