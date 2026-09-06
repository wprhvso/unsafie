"""platform: jobs, holds, cluster, metrics, credential semaphore

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06 06:30:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id BIGSERIAL PRIMARY KEY,
            kind VARCHAR(16) NOT NULL,
            bot_id INTEGER NOT NULL,
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            update_id BIGINT,
            turn_id UUID,
            lane VARCHAR(32) NOT NULL DEFAULT 'stable',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            resume VARCHAR(36),
            attempt INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 100,
            state VARCHAR(16) NOT NULL DEFAULT 'ready',
            run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
            lease_until TIMESTAMPTZ,
            worker VARCHAR(64),
            release_sha VARCHAR(64),
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_ready ON jobs (state, lane, priority, run_after)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_dedup ON jobs (bot_id, update_id) "
        "WHERE update_id IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_chat_running ON jobs (chat_id, state)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS holds (
            turn_id UUID PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount BIGINT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_holds_user_live ON holds (user_id, expires_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cluster_state (
            id INTEGER PRIMARY KEY,
            term BIGINT NOT NULL DEFAULT 0,
            leader VARCHAR(32),
            reason VARCHAR(255),
            durable BOOLEAN NOT NULL DEFAULT true,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("INSERT INTO cluster_state (id, term) VALUES (1, 0) ON CONFLICT DO NOTHING")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id VARCHAR(32) PRIMARY KEY,
            priority INTEGER NOT NULL DEFAULT 0,
            mesh_ip VARCHAR(64),
            domain VARCHAR(128),
            role VARCHAR(16),
            lsn VARCHAR(64),
            healthy BOOLEAN NOT NULL DEFAULT false,
            last_seen TIMESTAMPTZ
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS metric_samples (
            id BIGSERIAL PRIMARY KEY,
            node VARCHAR(32) NOT NULL,
            at TIMESTAMPTZ NOT NULL DEFAULT now(),
            values JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_metrics_node_at ON metric_samples (node, at)")

    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS lane VARCHAR(32) NOT NULL DEFAULT 'stable'")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS origin VARCHAR(16) NOT NULL DEFAULT 'user'")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS release_sha VARCHAR(64)")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS node VARCHAR(32)")

    op.execute(
        "ALTER TABLE anthropic_credentials ADD COLUMN IF NOT EXISTS in_flight INTEGER "
        "NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE anthropic_credentials ADD COLUMN IF NOT EXISTS max_concurrent INTEGER "
        "NOT NULL DEFAULT 4"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE anthropic_credentials DROP COLUMN IF EXISTS max_concurrent")
    op.execute("ALTER TABLE anthropic_credentials DROP COLUMN IF EXISTS in_flight")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS node")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS release_sha")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS origin")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS lane")
    op.execute("DROP TABLE IF EXISTS metric_samples")
    op.execute("DROP TABLE IF EXISTS nodes")
    op.execute("DROP TABLE IF EXISTS cluster_state")
    op.execute("DROP TABLE IF EXISTS holds")
    op.execute("DROP TABLE IF EXISTS jobs")
