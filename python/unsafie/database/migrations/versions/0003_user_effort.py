"""per-user effort

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05 07:30:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS effort VARCHAR(16)")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS effort")
