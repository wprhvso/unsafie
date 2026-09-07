"""money a running turn keeps reserved on the balance

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-07 12:50:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS locked BIGINT NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS locked")
