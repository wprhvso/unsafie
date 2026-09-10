from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS instance_id VARCHAR(64)")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_turns_alive ON turns (status, heartbeat_at)")
    op.execute("ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS trace_id VARCHAR(32)")
    op.execute("ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(64)")
    op.execute(
        "ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_pending "
        "ON webhook_deliveries (received_at) WHERE processed_at IS NULL",
    )
    op.execute(
        "UPDATE turns SET heartbeat_at = COALESCE(finished_at, created_at) "
        "WHERE heartbeat_at IS NULL",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_webhook_deliveries_pending")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN IF EXISTS attempts")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN IF EXISTS claimed_by")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN IF EXISTS claimed_at")
    op.execute("ALTER TABLE webhook_deliveries DROP COLUMN IF EXISTS trace_id")
    op.execute("DROP INDEX IF EXISTS ix_turns_alive")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS heartbeat_at")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS instance_id")
