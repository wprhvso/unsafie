from fastapi import APIRouter, HTTPException, status

from yet_another_claude_bot.api.dependencies.database import Session
from yet_another_claude_bot.api.schemas.user import Deposit, UserRead
from yet_another_claude_bot.repositories.user import UserRepository

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, session: Session) -> UserRead:
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user


@router.post("/{user_id}/deposit", response_model=UserRead)
async def deposit(user_id: int, payload: Deposit, session: Session) -> UserRead:
    return await UserRepository(session).deposit(user_id, payload.amount)
