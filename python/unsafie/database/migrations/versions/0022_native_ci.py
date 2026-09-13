from collections.abc import Sequence
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS ci_whitelist (
        github_login VARCHAR(255) PRIMARY KEY,
        added_by VARCHAR(255) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS ci_api_tokens (
        id BIGSERIAL PRIMARY KEY,
        github_login VARCHAR(255) NOT NULL REFERENCES ci_whitelist(github_login) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        token_hash VARCHAR(255) NOT NULL UNIQUE,
        token_prefix VARCHAR(32) NOT NULL,
        last_used_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS ci_secrets (
        repo_full_name VARCHAR(255) NOT NULL,
        key VARCHAR(255) NOT NULL,
        value TEXT NOT NULL,
        updated_by VARCHAR(255) NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (repo_full_name, key)
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS ci_runs (
        id BIGSERIAL PRIMARY KEY,
        installation_id BIGINT NOT NULL,
        repo_full_name VARCHAR(255) NOT NULL,
        commit_sha VARCHAR(64) NOT NULL,
        ref VARCHAR(255) NOT NULL,
        branch VARCHAR(255) NOT NULL,
        is_default_branch BOOLEAN NOT NULL DEFAULT FALSE,
        check_run_id BIGINT,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        trigger_event VARCHAR(64) NOT NULL DEFAULT 'push',
        sender VARCHAR(255),
        commit_message TEXT,
        lease_worker_id VARCHAR(255),
        lease_until TIMESTAMPTZ,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        exit_code INT,
        current_stage VARCHAR(16),
        error_message TEXT,
        log_path TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_ci_runs_pending ON ci_runs (id ASC) WHERE status = 'pending';")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ci_runs_stale ON ci_runs (lease_until) WHERE status = 'in_progress';")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ci_runs_repo ON ci_runs (repo_full_name, id DESC);")

    op.execute("""
    CREATE TABLE IF NOT EXISTS ci_run_metrics (
        id BIGSERIAL PRIMARY KEY,
        run_id BIGINT NOT NULL REFERENCES ci_runs(id) ON DELETE CASCADE,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        cpu_percent REAL NOT NULL,
        memory_rss_mb REAL NOT NULL,
        network_rx_kbps REAL NOT NULL,
        network_tx_kbps REAL NOT NULL
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ci_run_metrics_run ON ci_run_metrics (run_id, recorded_at ASC);")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ci_run_metrics CASCADE;")
    op.execute("DROP TABLE IF EXISTS ci_runs CASCADE;")
    op.execute("DROP TABLE IF EXISTS ci_secrets CASCADE;")
    op.execute("DROP TABLE IF EXISTS ci_api_tokens CASCADE;")
    op.execute("DROP TABLE IF EXISTS ci_whitelist CASCADE;")
