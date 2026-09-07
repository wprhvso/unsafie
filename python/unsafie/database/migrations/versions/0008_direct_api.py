from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESET = """
DO $$
DECLARE
    columns text;
BEGIN
    SELECT string_agg(format('%I = NULL', column_name), ', ')
    INTO columns
    FROM information_schema.columns
    WHERE table_name = 'turns' AND column_name IN ('session_id', 'transcript_lines');
    IF columns IS NOT NULL THEN
        EXECUTE 'UPDATE turns SET ' || columns;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute("DELETE FROM transcripts")
    op.execute(RESET)


def downgrade() -> None:
    op.execute("DELETE FROM transcripts")
    op.execute(RESET)
