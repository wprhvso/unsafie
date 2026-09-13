from collections.abc import Sequence
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS ci_jobs (
        id BIGSERIAL PRIMARY KEY,
        run_id BIGINT NOT NULL REFERENCES ci_runs(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        stage VARCHAR(16) NOT NULL,
        check_run_id BIGINT,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        exit_code INT,
        error_message TEXT,
        log_path TEXT,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ci_jobs_run ON ci_jobs (run_id, id ASC);")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ci_jobs CASCADE;")
