"""transcripts hold anthropic messages now

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-07 12:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM transcripts")
    op.execute("UPDATE turns SET session_id = NULL, transcript_lines = NULL")


def downgrade() -> None:
    op.execute("DELETE FROM transcripts")
    op.execute("UPDATE turns SET session_id = NULL, transcript_lines = NULL")
