from collections.abc import Sequence
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS ci_run_id BIGINT REFERENCES ci_runs(id) ON DELETE CASCADE;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_artifacts_ci_run ON artifacts(ci_run_id) WHERE kind = 'ci';")
    op.execute("ALTER TABLE ci_runs ADD COLUMN IF NOT EXISTS slug VARCHAR(16);")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_artifacts_ci_run;")
    op.execute("ALTER TABLE artifacts DROP COLUMN IF EXISTS ci_run_id;")
    op.execute("ALTER TABLE ci_runs DROP COLUMN IF EXISTS slug;")
