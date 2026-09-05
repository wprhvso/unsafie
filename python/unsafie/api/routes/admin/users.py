from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Page, PageParams
from unsafie.api.schemas.models import BudgetWrite, DepositWrite, TransactionRead, UserRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import GithubAccountRepository
from unsafie.database.repositories.user import UserRepository

router = APIRouter(prefix="/users", tags=["users"])


async def read(session, user) -> UserRead:
    logins = [a.login for a in await GithubAccountRepository(session).for_user(user.id)]
    return UserRead(
        **{
            k: getattr(user, k)
            for k in (
                "id",
                "balance",
                "budget",
                "locale",
                "timezone",
                "model",
                "effort",
                "git_name",
                "git_email",
            )
        },
        has_ssh_key=bool(user.ssh_public_key),
        github_logins=logins,
    )


@router.get("", response_model=Page[UserRead])
async def list_users(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await UserRepository(session).page(params.offset, params.limit)
        items = [await read(session, u) for u in rows]
    return Page.of(items, total, params)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int):
    async with SessionLocal() as session:
        user = await UserRepository(session).get(user_id)
        if user is None:
            raise HTTPException(404, "no such user")
        return await read(session, user)


@router.get("/{user_id}/transactions", response_model=list[TransactionRead])
async def user_transactions(user_id: int, limit: int = 50):
    async with SessionLocal() as session:
        return await UserRepository(session).transactions(user_id, limit)


@router.post("/{user_id}/deposit", response_model=UserRead)
async def deposit(user_id: int, body: DepositWrite):
    async with SessionLocal() as session:
        user = await UserRepository(session).deposit(user_id, body.amount)
        return await read(session, user)


@router.put("/{user_id}/budget", response_model=UserRead)
async def set_budget(user_id: int, body: BudgetWrite):
    async with SessionLocal() as session:
        user = await UserRepository(session).set_budget(user_id, body.budget)
        return await read(session, user)
