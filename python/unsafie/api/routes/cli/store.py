import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, select

from unsafie.api.routes.cli.deps import Pool, Secrets
from unsafie.database import SessionLocal
from unsafie.database.models.pool import UserKv, UserSecret
from unsafie.errors import OpsError
from unsafie.pool import blobs
from unsafie.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cli"])


class Pair(BaseModel):
    value: str


def _blob(row) -> dict:
    return {
        "key": row.key,
        "size": row.size,
        "sha256": row.sha256,
        "machine": row.machine,
        "created_at": row.created_at,
    }


@router.put("/blobs/{key:path}")
async def put_blob(key: str, request: Request, who: Pool) -> dict:
    data = await request.body()
    if len(data) > settings.pool_max_blob_item:
        raise HTTPException(413, f"over the {settings.pool_max_blob_item} byte limit for one blob")
    try:
        row = await blobs.put(who.user_id, key, data, who.machine)
    except OpsError as refused:
        raise HTTPException(409, str(refused)) from None
    return _blob(row)


@router.get("/blobs")
async def list_blobs(who: Pool, prefix: str = "", limit: int = 50) -> dict:
    rows = await blobs.listing(who.user_id, prefix, max(1, min(limit, 500)))
    return {"blobs": [_blob(row) for row in rows], "used": await blobs.used(who.user_id)}


@router.get("/blobs/{key:path}")
async def get_blob(key: str, who: Pool) -> Response:
    data = await blobs.get(who.user_id, key)
    if data is None:
        raise HTTPException(404, "no such key")
    return Response(content=data, media_type="application/octet-stream")


@router.delete("/blobs/{key:path}")
async def drop_blob(key: str, who: Pool) -> dict:
    return {"deleted": await blobs.remove(who.user_id, key)}


@router.get("/kv")
async def list_kv(who: Pool, prefix: str = "") -> dict:
    async with SessionLocal() as session:
        query = select(UserKv).where(UserKv.user_id == who.user_id)
        if prefix:
            query = query.where(UserKv.key.startswith(prefix))
        rows = await session.scalars(query.order_by(UserKv.key))
        return {"values": {row.key: row.value for row in rows}}


@router.get("/kv/{key:path}")
async def get_kv(key: str, who: Pool) -> dict:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(UserKv).where(UserKv.user_id == who.user_id, UserKv.key == key)
        )
    if row is None:
        raise HTTPException(404, "no such key")
    return {"key": row.key, "value": row.value, "updated_at": row.updated_at}


@router.put("/kv/{key:path}")
async def set_kv(key: str, body: Pair, who: Pool) -> dict:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(UserKv).where(UserKv.user_id == who.user_id, UserKv.key == key)
        )
        if row is None:
            row = UserKv(user_id=who.user_id, key=key[:255])
            session.add(row)
        row.value = body.value
        await session.commit()
    return {"key": key, "stored": len(body.value)}


@router.delete("/kv/{key:path}")
async def drop_kv(key: str, who: Pool) -> dict:
    async with SessionLocal() as session:
        done = await session.execute(
            delete(UserKv).where(UserKv.user_id == who.user_id, UserKv.key == key)
        )
        await session.commit()
    return {"deleted": bool(done.rowcount)}


@router.get("/secrets")
async def list_secrets(who: Secrets) -> dict:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(UserSecret).where(UserSecret.user_id == who.user_id).order_by(UserSecret.name)
        )
        return {"secrets": [{"name": row.name, "updated_at": row.updated_at} for row in rows]}


@router.get("/secrets/values")
async def secret_values(who: Secrets, prefix: str = "") -> dict:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(UserSecret).where(UserSecret.user_id == who.user_id).order_by(UserSecret.name)
        )
        return {"values": {f"{prefix}{row.name}": row.value for row in rows}}


@router.get("/secrets/{name}")
async def get_secret(name: str, who: Secrets) -> dict:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(UserSecret).where(UserSecret.user_id == who.user_id, UserSecret.name == name)
        )
    if row is None:
        raise HTTPException(404, "no such secret")
    return {"name": row.name, "value": row.value}


@router.put("/secrets/{name}")
async def set_secret(name: str, body: Pair, who: Secrets) -> dict:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(UserSecret).where(UserSecret.user_id == who.user_id, UserSecret.name == name)
        )
        if row is None:
            row = UserSecret(user_id=who.user_id, name=name[:128])
            session.add(row)
        row.value = body.value
        await session.commit()
    logger.info("%s secret %s stored", who.prefix, name)
    return {"name": name, "stored": True}


@router.delete("/secrets/{name}")
async def drop_secret(name: str, who: Secrets) -> dict:
    async with SessionLocal() as session:
        done = await session.execute(
            delete(UserSecret).where(UserSecret.user_id == who.user_id, UserSecret.name == name)
        )
        await session.commit()
    return {"deleted": bool(done.rowcount)}
