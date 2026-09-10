import asyncio
import hashlib
import logging
from pathlib import Path

from sqlalchemy import delete, func, select

from unsafie.database import SessionLocal
from unsafie.database.models.pool import PoolBlob
from unsafie.errors import OpsError
from unsafie.settings import settings

logger = logging.getLogger(__name__)


class BlobError(OpsError):
    pass


def clean(key: str) -> str:
    stripped = (key or "").strip().strip("/")
    if not stripped or ".." in stripped.split("/"):
        msg = f"'{key}' is not a usable key"
        raise BlobError(msg)
    return stripped[:512]


def path_of(user_id: int, key: str) -> Path:
    digest = hashlib.sha256(f"{user_id}:{key}".encode()).hexdigest()
    return settings.pool_blob_dir / str(user_id) / digest[:2] / digest


async def put(user_id: int, key: str, data: bytes, machine: str | None = None) -> PoolBlob:
    key = clean(key)
    if len(data) > settings.pool_max_blob_item:
        msg = f"{len(data)} bytes is over the {settings.pool_max_blob_item} byte limit for one blob"
        raise BlobError(
            msg,
        )
    held = await used(user_id)
    if held + len(data) > settings.pool_max_blob_bytes:
        msg = (
            f"your blobs would take {held + len(data)} bytes, the limit is "
            f"{settings.pool_max_blob_bytes}; delete something with `unsafie blob rm`"
        )
        raise BlobError(
            msg,
        )
    target = path_of(user_id, key)
    await asyncio.to_thread(_write, target, data)
    digest = hashlib.sha256(data).hexdigest()
    async with SessionLocal() as session:
        row = await session.scalar(
            select(PoolBlob).where(PoolBlob.user_id == user_id, PoolBlob.key == key),
        )
        if row is None:
            row = PoolBlob(user_id=user_id, key=key)
            session.add(row)
        row.size = len(data)
        row.sha256 = digest
        row.machine = machine
        await session.commit()
        await session.refresh(row)
    return row


def _write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    spool = target.with_suffix(".part")
    spool.write_bytes(data)
    spool.replace(target)


async def get(user_id: int, key: str) -> bytes | None:
    key = clean(key)
    target = path_of(user_id, key)
    if not await asyncio.to_thread(target.is_file):
        return None
    return await asyncio.to_thread(target.read_bytes)


async def head(user_id: int, key: str) -> PoolBlob | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(PoolBlob).where(PoolBlob.user_id == user_id, PoolBlob.key == clean(key)),
        )


async def listing(user_id: int, prefix: str = "", limit: int = 50) -> list[PoolBlob]:
    async with SessionLocal() as session:
        query = select(PoolBlob).where(PoolBlob.user_id == user_id)
        if prefix:
            query = query.where(PoolBlob.key.startswith(prefix))
        rows = await session.scalars(query.order_by(PoolBlob.created_at.desc()).limit(limit))
        return list(rows)


async def remove(user_id: int, key: str) -> bool:
    key = clean(key)
    target = path_of(user_id, key)
    await asyncio.to_thread(target.unlink, True)
    async with SessionLocal() as session:
        done = await session.execute(
            delete(PoolBlob).where(PoolBlob.user_id == user_id, PoolBlob.key == key),
        )
        await session.commit()
    return bool(getattr(done, "rowcount", 0))


async def used(user_id: int) -> int:
    async with SessionLocal() as session:
        total = await session.scalar(
            select(func.coalesce(func.sum(PoolBlob.size), 0)).where(PoolBlob.user_id == user_id),
        )
    return int(total or 0)
