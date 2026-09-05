import logging

import asyncssh

from unsafie.database import SessionLocal
from unsafie.database.repositories.user import UserRepository
from unsafie.ssh.errors import SshError

logger = logging.getLogger(__name__)

KEY_TYPE = "ssh-ed25519"


def generate(comment: str) -> tuple[str, str]:
    key = asyncssh.generate_private_key(KEY_TYPE, comment=comment)
    private = key.export_private_key().decode()
    public = key.export_public_key().decode().strip()
    return private, public


async def get(user_id: int) -> tuple[str, str] | None:
    async with SessionLocal() as session:
        user = await UserRepository(session).get(user_id)
    if user is None or not user.ssh_private_key or not user.ssh_public_key:
        return None
    return user.ssh_private_key, user.ssh_public_key


async def ensure(user_id: int) -> tuple[str, str]:
    existing = await get(user_id)
    if existing is not None:
        return existing
    private, public = generate(f"unsafie-{user_id}")
    async with SessionLocal() as session:
        users = UserRepository(session)
        user = await users.get_or_create(user_id)
        user.ssh_private_key = private
        user.ssh_public_key = public
        await session.commit()
    logger.info("user=%s ssh key generated", user_id)
    return private, public


async def rotate(user_id: int) -> tuple[str, str]:
    private, public = generate(f"unsafie-{user_id}")
    async with SessionLocal() as session:
        users = UserRepository(session)
        user = await users.get_or_create(user_id)
        user.ssh_private_key = private
        user.ssh_public_key = public
        await session.commit()
    logger.info("user=%s ssh key rotated", user_id)
    return private, public


def load(private: str) -> asyncssh.SSHKey:
    try:
        return asyncssh.import_private_key(private)
    except (asyncssh.KeyImportError, ValueError) as e:
        raise SshError(f"stored ssh key is broken: {e}") from e
