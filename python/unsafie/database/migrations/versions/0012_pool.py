from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "pool_ci_jobs",
    "pool_ci_repos",
    "pool_usage",
    "pool_leases",
    "pool_commands",
    "pool_blobs",
    "pool_machines",
    "pool_donors",
    "user_kv",
    "user_secrets",
    "api_tokens",
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_tokens (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users (id) ON DELETE CASCADE,
            bot_id INTEGER REFERENCES bots (id) ON DELETE CASCADE,
            chat_id BIGINT,
            name VARCHAR(64) NOT NULL,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            scopes VARCHAR(255) NOT NULL DEFAULT '',
            kind VARCHAR(8) NOT NULL DEFAULT 'human',
            machine VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_tokens_user ON api_tokens (user_id, revoked_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_donors (
            id SERIAL PRIMARY KEY,
            login VARCHAR(255) NOT NULL UNIQUE,
            label VARCHAR(64),
            token TEXT NOT NULL,
            repo VARCHAR(255) NOT NULL,
            workflow VARCHAR(128) NOT NULL DEFAULT 'unsafie.yml',
            jobs INTEGER NOT NULL DEFAULT 20,
            worker_token_hash VARCHAR(64),
            enabled BOOLEAN NOT NULL DEFAULT true,
            state VARCHAR(32) NOT NULL DEFAULT 'new',
            last_error TEXT,
            rate_remaining INTEGER,
            minutes_month INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reconciled_at TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_machines (
            id SERIAL PRIMARY KEY,
            name VARCHAR(64) NOT NULL UNIQUE,
            alias VARCHAR(32),
            donor_id INTEGER REFERENCES pool_donors (id) ON DELETE SET NULL,
            run_id BIGINT,
            profile VARCHAR(16) NOT NULL DEFAULT 'fast',
            state VARCHAR(16) NOT NULL DEFAULT 'idle',
            user_id BIGINT REFERENCES users (id) ON DELETE SET NULL,
            chat_id BIGINT,
            labels VARCHAR(255) NOT NULL DEFAULT '',
            facts JSONB NOT NULL DEFAULT '{}'::jsonb,
            boot_seconds DOUBLE PRECISION,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            leased_at TIMESTAMPTZ,
            gone_at TIMESTAMPTZ,
            gone_reason VARCHAR(64)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pool_machines_state ON pool_machines (state, seen_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pool_machines_user ON pool_machines (user_id, state)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_commands (
            id UUID PRIMARY KEY,
            machine VARCHAR(64) NOT NULL,
            user_id BIGINT REFERENCES users (id) ON DELETE SET NULL,
            turn_id UUID REFERENCES turns (id) ON DELETE SET NULL,
            command TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'queued',
            exit_code INTEGER,
            bytes INTEGER NOT NULL DEFAULT 0,
            background BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pool_commands_machine ON pool_commands (machine, created_at)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_pool_commands_user ON pool_commands (user_id, created_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_blobs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            key VARCHAR(512) NOT NULL,
            size BIGINT NOT NULL DEFAULT 0,
            sha256 VARCHAR(64) NOT NULL DEFAULT '',
            machine VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, key)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_leases (
            id SERIAL PRIMARY KEY,
            machine VARCHAR(64) NOT NULL,
            user_id BIGINT REFERENCES users (id) ON DELETE SET NULL,
            chat_id BIGINT,
            turn_id UUID,
            taken_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            released_at TIMESTAMPTZ,
            reason VARCHAR(64),
            commands INTEGER NOT NULL DEFAULT 0,
            seconds DOUBLE PRECISION
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pool_leases_user ON pool_leases (user_id, taken_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_usage (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            day DATE NOT NULL,
            machine_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
            ci_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
            commands INTEGER NOT NULL DEFAULT 0,
            UNIQUE (user_id, day)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_ci_repos (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            slug VARCHAR(255) NOT NULL,
            label VARCHAR(64) NOT NULL DEFAULT 'pool',
            jobs INTEGER NOT NULL DEFAULT 5,
            idle INTEGER NOT NULL DEFAULT 300,
            lifetime INTEGER NOT NULL DEFAULT 3600,
            enabled BOOLEAN NOT NULL DEFAULT true,
            scale_set_id INTEGER,
            state VARCHAR(32) NOT NULL DEFAULT 'new',
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reconciled_at TIMESTAMPTZ,
            UNIQUE (user_id, slug)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS pool_ci_jobs (
            id SERIAL PRIMARY KEY,
            repo_id INTEGER NOT NULL REFERENCES pool_ci_repos (id) ON DELETE CASCADE,
            run_id BIGINT,
            job VARCHAR(255),
            machine VARCHAR(64),
            status VARCHAR(32) NOT NULL DEFAULT 'assigned',
            result VARCHAR(32),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pool_ci_jobs_repo ON pool_ci_jobs (repo_id, started_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_secrets (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            name VARCHAR(128) NOT NULL,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, name)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_kv (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            key VARCHAR(255) NOT NULL,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, key)
        )
    """)

    for column, kind, default in (
        ("pool_max_machines", "INTEGER", "3"),
        ("pool_max_background", "INTEGER", "10"),
        ("pool_max_minutes_day", "INTEGER", "600"),
        ("pool_max_machines_day", "INTEGER", "100"),
        ("pool_priority", "INTEGER", "0"),
        ("pool_blocked", "BOOLEAN", "false"),
    ):
        op.execute(
            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column} {kind} NOT NULL DEFAULT {default}"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for column in (
        "pool_max_machines",
        "pool_max_background",
        "pool_max_minutes_day",
        "pool_max_machines_day",
        "pool_priority",
        "pool_blocked",
    ):
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {column}")
