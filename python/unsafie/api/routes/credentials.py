from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from yet_another_claude_bot.agent.credentials import mask
from yet_another_claude_bot.api.dependencies.database import Session
from yet_another_claude_bot.api.schemas.credential import (
    CredentialCreate,
    CredentialRead,
    CredentialUpdate,
)
from yet_another_claude_bot.models.credential import AnthropicCredential
from yet_another_claude_bot.repositories.credential import CredentialRepository

router = APIRouter(prefix="/credentials", tags=["credentials"])


def _read(row: AnthropicCredential) -> CredentialRead:
    return CredentialRead(
        id=row.id,
        kind=row.kind,
        secret=mask(row.secret),
        label=row.label,
        enabled=row.enabled,
        failures=row.failures,
        cooldown_until=row.cooldown_until,
        last_error=row.last_error,
        last_used_at=row.last_used_at,
        uses=row.uses,
        total_cost_usd=row.total_cost_usd,
        created_at=row.created_at,
    )


@router.get("", response_model=list[CredentialRead])
async def list_credentials(session: Session) -> list[CredentialRead]:
    return [_read(r) for r in await CredentialRepository(session).list()]


@router.post("", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(payload: CredentialCreate, session: Session) -> CredentialRead:
    try:
        row = await CredentialRepository(session).create(
            payload.kind, payload.secret.strip(), payload.label
        )
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "secret already exists")
    return _read(row)


@router.patch("/{credential_id}", response_model=CredentialRead)
async def update_credential(
    credential_id: int, payload: CredentialUpdate, session: Session
) -> CredentialRead:
    row = await CredentialRepository(session).update(
        credential_id, enabled=payload.enabled, label=payload.label, reset=payload.reset
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return _read(row)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(credential_id: int, session: Session) -> None:
    if not await CredentialRepository(session).delete(credential_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
