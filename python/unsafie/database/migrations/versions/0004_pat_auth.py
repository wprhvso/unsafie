"""personal access tokens instead of oauth

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05 16:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Written with IF EXISTS: a database created straight from the models is already like this.
    op.execute("DROP TABLE IF EXISTS oauth_states")
    # OAuth tokens are worthless now: everyone has to hand over a PAT with /gh <token>.
    op.execute("UPDATE github_accounts SET token = NULL")
    op.execute("ALTER TABLE github_accounts ADD COLUMN IF NOT EXISTS scopes TEXT")
    op.execute("ALTER TABLE github_accounts DROP COLUMN IF EXISTS token_expires")
    op.execute("ALTER TABLE github_accounts DROP COLUMN IF EXISTS refresh_token")
    op.execute("ALTER TABLE github_accounts DROP COLUMN IF EXISTS refresh_expires")
    # A repository may now be known from a token alone, without an installation behind it.
    op.execute("ALTER TABLE repos ALTER COLUMN installation_id DROP NOT NULL")
    op.execute("ALTER TABLE repos DROP CONSTRAINT IF EXISTS repos_installation_id_fkey")
    op.execute(
        "ALTER TABLE repos ADD CONSTRAINT repos_installation_id_fkey "
        "FOREIGN KEY (installation_id) REFERENCES installations(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("DELETE FROM repos WHERE installation_id IS NULL")
    op.execute("ALTER TABLE repos DROP CONSTRAINT IF EXISTS repos_installation_id_fkey")
    op.execute(
        "ALTER TABLE repos ADD CONSTRAINT repos_installation_id_fkey "
        "FOREIGN KEY (installation_id) REFERENCES installations(id) ON DELETE CASCADE"
    )
    op.execute("ALTER TABLE repos ALTER COLUMN installation_id SET NOT NULL")
    op.add_column(
        "github_accounts",
        sa.Column("refresh_expires", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("github_accounts", sa.Column("refresh_token", sa.Text(), nullable=True))
    op.add_column(
        "github_accounts",
        sa.Column("token_expires", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column("github_accounts", "scopes")
    op.create_table(
        "oauth_states",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
