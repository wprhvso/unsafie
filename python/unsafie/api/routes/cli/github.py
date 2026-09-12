from unsafie.log import get_logger
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from unsafie.api.routes.cli.deps import Accounts, Github
from unsafie.database import SessionLocal
from unsafie.database.models.repo import Repo
from unsafie.database.repositories.github import (
    GithubAccountRepository,
    UserRepoRepository,
)
from unsafie.github import pat
from unsafie.github.app import auth
from unsafie.github.client.base import GithubHTTP
from unsafie.github.errors import GithubError

logger = get_logger(__name__)

router = APIRouter(prefix="/github", tags=["cli"])


class TokenIn(BaseModel):
    token: str


class RepoIn(BaseModel):
    ref: str
    alias: str | None = None


class ShortToken(BaseModel):
    repo: str | None = None
    minutes: int = 60
    login: str | None = None


class ApiCall(BaseModel):
    path: str
    method: str = "GET"
    body: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    login: str | None = None


def _repo(row: Repo, alias: str | None = None) -> dict:
    return {
        "slug": f"{row.owner}/{row.name}",
        "alias": alias,
        "default_branch": row.default_branch,
        "private": row.private,
        "installed": row.installation_id is not None,
    }


async def _identity(user_id: int, login: str) -> tuple[str, str]:
    return await pat.identity(user_id, login)


@router.get("/accounts")
async def accounts(who: Github) -> dict:
    rows = await pat.accounts_of(who.user_id)
    out = []
    for row in rows:
        name, email = await _identity(who.user_id, row.login)
        out.append(
            {
                "login": row.login,
                "scopes": row.scopes,
                "has_token": bool(row.token),
                "created_at": row.created_at,
                "name": name,
                "email": email,
            },
        )
    return {"accounts": out}


@router.post("/accounts")
async def add_account(body: TokenIn, who: Accounts) -> dict:
    try:
        account, scopes = await pat.save(who.user_id, body.token.strip())
    except GithubError as refused:
        raise HTTPException(400, str(refused)) from None
    return {"login": account.login, "scopes": scopes, "note": "same login replaces its token"}


@router.delete("/accounts/{login}")
async def drop_account(login: str, who: Accounts) -> dict:
    gone = await pat.forget(who.user_id, login)
    if gone is None:
        raise HTTPException(404, f"no account '{login}'")
    return {"login": login, "removed": True}


@router.get("/repos")
async def repos(who: Github, limit: int = 100) -> dict:
    async with SessionLocal() as session:
        rows = await UserRepoRepository(session).for_user(who.user_id)
    return {"repos": [_repo(repo, binding.alias) for binding, repo in rows[:limit]]}


@router.post("/repos")
async def add_repo(body: RepoIn, who: Github) -> dict:
    try:
        row, alias = await pat.add(who.user_id, body.ref, body.alias)
    except GithubError as refused:
        raise HTTPException(400, str(refused)) from None
    return _repo(row, alias)


@router.delete("/repos/{ref:path}")
async def drop_repo(ref: str, who: Github) -> dict:
    async with SessionLocal() as session:
        gone = await UserRepoRepository(session).unbind(who.user_id, ref)
    if gone is None:
        raise HTTPException(404, f"no repository '{ref}'")
    return {"ref": ref, "removed": True}


@router.post("/repos/sync")
async def sync_repos(who: Github) -> dict:
    account = await pat.account_of(who.user_id)
    if account is None:
        raise HTTPException(400, "no github account: unsafie account add ghp_…")
    saved = await pat.sync(account)
    return {"account": account.login, "repos": len(saved)}


@router.post("/token")
async def short_token(body: ShortToken, who: Github) -> dict:
    if body.repo:
        row = await _find(who.user_id, body.repo)
        if row is not None and row.installation_id:
            try:
                token = await auth.installation_token(row.installation_id)
            except GithubError as refused:
                logger.info("installation token for %s failed: %s", body.repo, refused)
            else:
                account = await pat.account_of(who.user_id, body.login)
                login = account.login if account else ""
                name, email = await _identity(who.user_id, login) if login else ("", "")
                return {
                    "token": token,
                    "kind": "installation",
                    "repo": f"{row.owner}/{row.name}",
                    "minutes": 60,
                    "name": name,
                    "email": email,
                }
    account = await _account(who.user_id, body.login)
    async with SessionLocal() as db:
        await GithubAccountRepository(db).touch(account.id)
    name, email = await pat.identity(who.user_id, account.login)
    return {
        "token": account.token,
        "kind": "pat",
        "login": account.login,
        "name": name,
        "email": email,
        "note": "this is your personal token, not a scoped one; it lives as long as you keep it",
    }


async def _account(user_id: int, login: str | None):
    account = await pat.account_of(user_id, login)
    if account is None or not account.token:
        known = ", ".join(row.login for row in await pat.accounts_of(user_id)) or "none"
        raise HTTPException(
            400,
            f"no github account '{login}'. Attached: {known}. Add one with /gh <token> in the chat",
        )
    return account


@router.post("/api")
async def call_api(body: ApiCall, who: Github) -> dict:
    account = await _account(who.user_id, body.login)
    if body.path.startswith(("http://", "https://", "//")) or "://" in body.path:
        raise HTTPException(400, "only relative GitHub API paths are allowed")
    path = body.path if body.path.startswith("/") else f"/{body.path}"
    try:
        answer = await GithubHTTP(account.token).request(
            body.method.upper(), path, params=body.params, json_body=body.body,
        )
    except GithubError as refused:
        raise HTTPException(400, str(refused)) from None
    return {"result": answer}


async def _find(user_id: int, ref: str) -> Repo | None:
    async with SessionLocal() as session:
        found = await UserRepoRepository(session).resolve(user_id, ref)
        if found is not None:
            return found[1]
    return None
