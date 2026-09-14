from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("ALTER TABLE ci_run_metrics ADD COLUMN IF NOT EXISTS job_name VARCHAR(255);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ci_run_metrics_job ON ci_run_metrics (run_id, job_name, recorded_at ASC);")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ci_run_metrics_job;")
    op.execute("ALTER TABLE ci_run_metrics DROP COLUMN IF EXISTS job_name;")
