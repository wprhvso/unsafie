from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS turn_checkpoints (
            id BIGSERIAL PRIMARY KEY,
            turn_id UUID NOT NULL REFERENCES turns (id) ON DELETE CASCADE,
            step INTEGER NOT NULL,
            phase VARCHAR(32) NOT NULL,
            messages BYTEA NOT NULL,
            active_block JSONB,
            injected JSONB,
            credential_id INTEGER REFERENCES opal_sessions (id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_turn_checkpoints_step_phase UNIQUE (turn_id, step, phase)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_turn_checkpoints_lookup ON turn_checkpoints (turn_id, step DESC, created_at DESC)"
    )
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS recovery_attempts INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS last_checkpoint_step INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE turns ADD COLUMN IF NOT EXISTS active_spool_dir VARCHAR(255)")
    op.execute(
        "ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS active_turn_id UUID REFERENCES turns (id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_turn ON scheduled_tasks (active_turn_id) WHERE active_turn_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scheduled_tasks_turn")
    op.execute("ALTER TABLE scheduled_tasks DROP COLUMN IF EXISTS active_turn_id")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS active_spool_dir")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS last_checkpoint_step")
    op.execute("ALTER TABLE turns DROP COLUMN IF EXISTS recovery_attempts")
    op.execute("DROP TABLE IF EXISTS turn_checkpoints")
