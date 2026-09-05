import logging

from fastapi import APIRouter, HTTPException, status

from yet_another_claude_bot.api.dependencies.database import Session
from yet_another_claude_bot.api.schemas.github import (
    GitAuthor,
    GithubRead,
    GithubToken,
    RepoAdd,
    RepoRead,
    WorktreeRead,
)
from yet_another_claude_bot.github import binding
from yet_another_claude_bot.github.errors import GitHubError, OpsError
from yet_another_claude_bot.repositories.github import GithubRepository
from yet_another_claude_bot.repositories.user import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github"])


def _err(e: Exception) -> HTTPException:
    if isinstance(e, OpsError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if isinstance(e, GitHubError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, e.message)
    raise e


@router.get("/users/{user_id}/github", response_model=GithubRead)
async def get_github(user_id: int, session: Session):
    user = await UserRepository(session).get(user_id)
    return GithubRead(login=user.github_login if user else None)


@router.put("/users/{user_id}/github", response_model=GithubRead)
async def github_login(user_id: int, payload: GithubToken, session: Session):
    try:
        login = await binding.login(session, user_id, payload.token)
    except (OpsError, GitHubError) as e:
        raise _err(e)
    return GithubRead(login=login)


@router.delete("/users/{user_id}/github", status_code=status.HTTP_204_NO_CONTENT)
async def github_logout(user_id: int, session: Session) -> None:
    if not await binding.logout(session, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.get("/users/{user_id}/repos", response_model=list[RepoRead])
async def list_repos(user_id: int, session: Session):
    return await GithubRepository(session).repos(user_id)


@router.post("/users/{user_id}/repos", response_model=RepoRead, status_code=status.HTTP_201_CREATED)
async def add_repo(user_id: int, payload: RepoAdd, session: Session):
    try:
        return await binding.add_repo(session, user_id, payload.repo, payload.alias)
    except (OpsError, GitHubError) as e:
        raise _err(e)


@router.delete("/users/{user_id}/repos/{alias}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_repo(user_id: int, alias: str, session: Session) -> None:
    try:
        await binding.remove_repo(session, user_id, alias)
    except OpsError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.get("/users/{user_id}/worktrees", response_model=list[WorktreeRead])
async def list_worktrees(user_id: int, session: Session):
    rows = await GithubRepository(session).worktrees(user_id)
    return [
        WorktreeRead(
            repo=r.alias,
            branch=w.branch,
            base_commit_sha=w.base_commit_sha,
            changes=len(w.changes or {}),
            pending=(w.pending or {}).get("kind"),
            stash=bool(w.stash),
        )
        for r, w in rows
    ]


@router.put("/users/{user_id}/git", status_code=status.HTTP_204_NO_CONTENT)
async def set_author(user_id: int, payload: GitAuthor, session: Session) -> None:
    try:
        await binding.set_author(session, user_id, payload.name, payload.email)
    except OpsError as e:
        raise _err(e)
