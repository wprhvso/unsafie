from fastapi import APIRouter, HTTPException

from unsafie.agent.credentials import mask
from unsafie.api.schemas.models import CredentialPatch, CredentialRead, CredentialWrite
from unsafie.database import SessionLocal
from unsafie.database.models.credential import CredentialKind
from unsafie.database.repositories.credential import CredentialRepository

router = APIRouter(prefix="/credentials", tags=["credentials"])


def read(row) -> CredentialRead:
    return CredentialRead(**{**row.__dict__, "secret_masked": mask(row.secret)})


@router.get("", response_model=list[CredentialRead])
async def list_credentials():
    async with SessionLocal() as session:
        return [read(r) for r in await CredentialRepository(session).all()]


@router.post("", response_model=CredentialRead, status_code=201)
async def add_credential(body: CredentialWrite):
    if body.kind not in (CredentialKind.API_KEY, CredentialKind.OAUTH):
        raise HTTPException(422, "kind must be api_key or oauth")
    async with SessionLocal() as session:
        row = await CredentialRepository(session).create(
            CredentialKind(body.kind), body.secret.strip(), body.label
        )
    return read(row)


@router.patch("/{credential_id}", response_model=CredentialRead)
async def patch_credential(credential_id: int, body: CredentialPatch):
    async with SessionLocal() as session:
        row = await CredentialRepository(session).update(
            credential_id, enabled=body.enabled, label=body.label, reset=body.reset
        )
    if row is None:
        raise HTTPException(404, "no such credential")
    return read(row)


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(credential_id: int):
    async with SessionLocal() as session:
        if not await CredentialRepository(session).delete(credential_id):
            raise HTTPException(404, "no such credential")
