"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-04 12:00:00

"""

from collections.abc import Sequence

from alembic import op

import unsafie.database.models  # noqa: F401
from unsafie.database import Base

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IN_TSV = "to_tsvector('simple', coalesce(payload #>> '{message,text}', payload #>> '{message,caption}', ''))"


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())
    op.execute(
        "INSERT INTO config (id, ratio, oauth_ratio) VALUES (1, 1, 0.5) ON CONFLICT DO NOTHING"
    )
    op.execute(f"CREATE INDEX ix_updates_fts ON updates USING gin ({IN_TSV})")
    op.execute(
        "CREATE INDEX ix_responses_fts ON responses USING gin (to_tsvector('simple', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_responses_fts")
    op.execute("DROP INDEX IF EXISTS ix_updates_fts")
    Base.metadata.drop_all(op.get_bind())
