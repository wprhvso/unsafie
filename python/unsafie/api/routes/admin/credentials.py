from fastapi import APIRouter, HTTPException

from unsafie.agent import opal
from unsafie.agent.credentials import mask
from unsafie.api.schemas.models import OpalSessionPatch, OpalSessionRead, OpalSessionWrite
from unsafie.database import SessionLocal
from unsafie.database.repositories.opal_session import OpalSessionRepository

router = APIRouter(prefix="/credentials", tags=["credentials"])


def read(row) -> OpalSessionRead:
    return OpalSessionRead(
        id=row.id,
        label=row.label,
        refresh_token_masked=mask(row.refresh_token),
        enabled=row.enabled,
        failures=row.failures,
        cooldown_until=row.cooldown_until,
        last_error=row.last_error,
        last_used_at=row.last_used_at,
        uses=row.uses,
        created_at=row.created_at,
    )


@router.get("", response_model=list[OpalSessionRead])
async def list_credentials():
    async with SessionLocal() as session:
        return [read(r) for r in await OpalSessionRepository(session).all()]


@router.post("", response_model=OpalSessionRead, status_code=201)
async def add_credential(body: OpalSessionWrite):
    token = body.refresh_token.strip()
    try:
        await opal.refresh_access_token(token)
    except opal.OpalRefreshFailed as e:
        raise HTTPException(400, f"invalid refresh token: {e}") from None
    async with SessionLocal() as session:
        row = await OpalSessionRepository(session).create(token, body.label)
    return read(row)


@router.post("/{session_id}/refresh", response_model=OpalSessionRead)
async def refresh_credential(session_id: int):
    async with SessionLocal() as session:
        repo = OpalSessionRepository(session)
        row = await repo.get(session_id)
        if row is None:
            raise HTTPException(404, "no such opal session")
        try:
            await opal.get_access_token(row.id, row.refresh_token)
            await repo.succeeded(row.id)
        except opal.OpalRefreshFailed as e:
            await repo.failed(row.id, error=str(e), cooldown_until=None, disable=False)
            raise HTTPException(400, f"refresh failed: {e}") from None
        row = await repo.get(session_id)
    return read(row)


@router.patch("/{session_id}", response_model=OpalSessionRead)
async def patch_credential(session_id: int, body: OpalSessionPatch):
    async with SessionLocal() as session:
        row = await OpalSessionRepository(session).update(
            session_id, enabled=body.enabled, label=body.label, reset=body.reset,
        )
    if row is None:
        raise HTTPException(404, "no such opal session")
    return read(row)


@router.delete("/{session_id}", status_code=204)
async def delete_credential(session_id: int) -> None:
    await opal.invalidate(session_id)
    async with SessionLocal() as session:
        if not await OpalSessionRepository(session).delete(session_id):
            raise HTTPException(404, "no such opal session")
