from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from unsafie.crypto import decrypt, encrypt

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        text("SELECT id, token FROM github_accounts WHERE token IS NOT NULL AND token != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec == val:
            enc = encrypt(val)
            conn.execute(
                text("UPDATE github_accounts SET token = :val WHERE id = :id"),
                {"val": enc, "id": row_id},
            )

    rows = conn.execute(
        text("SELECT id, ssh_private_key FROM users WHERE ssh_private_key IS NOT NULL AND ssh_private_key != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec == val:
            enc = encrypt(val)
            conn.execute(
                text("UPDATE users SET ssh_private_key = :val WHERE id = :id"),
                {"val": enc, "id": row_id},
            )

    rows = conn.execute(
        text("SELECT id, value FROM user_secrets WHERE value IS NOT NULL AND value != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec == val:
            enc = encrypt(val)
            conn.execute(
                text("UPDATE user_secrets SET value = :val WHERE id = :id"),
                {"val": enc, "id": row_id},
            )

    rows = conn.execute(
        text("SELECT id, token FROM pool_donors WHERE token IS NOT NULL AND token != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec == val:
            enc = encrypt(val)
            conn.execute(
                text("UPDATE pool_donors SET token = :val WHERE id = :id"),
                {"val": enc, "id": row_id},
            )


def downgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        text("SELECT id, token FROM github_accounts WHERE token IS NOT NULL AND token != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec != val:
            conn.execute(
                text("UPDATE github_accounts SET token = :val WHERE id = :id"),
                {"val": dec, "id": row_id},
            )

    rows = conn.execute(
        text("SELECT id, ssh_private_key FROM users WHERE ssh_private_key IS NOT NULL AND ssh_private_key != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec != val:
            conn.execute(
                text("UPDATE users SET ssh_private_key = :val WHERE id = :id"),
                {"val": dec, "id": row_id},
            )

    rows = conn.execute(
        text("SELECT id, value FROM user_secrets WHERE value IS NOT NULL AND value != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec != val:
            conn.execute(
                text("UPDATE user_secrets SET value = :val WHERE id = :id"),
                {"val": dec, "id": row_id},
            )

    rows = conn.execute(
        text("SELECT id, token FROM pool_donors WHERE token IS NOT NULL AND token != ''")
    ).fetchall()
    for row_id, val in rows:
        dec = decrypt(val)
        if dec != val:
            conn.execute(
                text("UPDATE pool_donors SET token = :val WHERE id = :id"),
                {"val": dec, "id": row_id},
            )
