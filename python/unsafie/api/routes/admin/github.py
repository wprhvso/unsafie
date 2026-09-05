from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Ok, Page, PageParams
from unsafie.api.schemas.models import (
    GithubAccountRead,
    GithubAppRead,
    InstallationRead,
    RepoRead,
    WorktreeRead,
)
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import (
    GithubAccountRepository,
    GithubAppRepository,
    InstallationRepository,
    RepoRepository,
    WorktreeRepository,
)
from unsafie.github.app import auth, manifest
from unsafie.settings import settings

router = APIRouter(prefix="/github", tags=["github"])


@router.get("/app")
async def get_app():
    async with SessionLocal() as session:
        app = await GithubAppRepository(session).get()
    if app is None:
        return {
            "configured": False,
            "create_url": f"{settings.github_origin}/gh/app/new",
            "webhook_url": manifest.webhook_url(),
            "redirect_url": manifest.redirect_url(),
            "permissions": manifest.PERMISSIONS,
            "events": manifest.EVENTS,
        }
    return {
        "configured": True,
        "app": GithubAppRead.model_validate(app).model_dump(),
        "install_url": manifest.install_url(app.slug),
        "webhook_url": manifest.webhook_url(),
    }


@router.delete("/app", response_model=Ok)
async def forget_app():
    async with SessionLocal() as session:
        if not await GithubAppRepository(session).delete():
            raise HTTPException(404, "the app is not configured")
    return Ok(detail="app credentials removed; create a new app to continue")


@router.get("/accounts", response_model=Page[GithubAccountRead])
async def list_accounts(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await GithubAccountRepository(session).page(params.offset, params.limit)
    items = [GithubAccountRead(**{**r.__dict__, "has_token": bool(r.token)}) for r in rows]
    return Page.of(items, total, params)


@router.get("/installations", response_model=list[InstallationRead])
async def list_installations():
    async with SessionLocal() as session:
        rows = await InstallationRepository(session).all()
    return [InstallationRead.model_validate(r) for r in rows]


@router.delete("/installations/{installation_id}", response_model=Ok)
async def forget_installation(installation_id: int):
    async with SessionLocal() as session:
        if not await InstallationRepository(session).delete(installation_id):
            raise HTTPException(404, "no such installation")
    auth.forget_installation(installation_id)
    return Ok(detail="installation forgotten; its repositories stay, they are served by tokens")


@router.get("/repos", response_model=Page[RepoRead])
async def list_repos(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await RepoRepository(session).page(params.offset, params.limit)
    return Page.of([RepoRead.model_validate(r) for r in rows], total, params)


@router.get("/worktrees", response_model=Page[WorktreeRead])
async def list_worktrees(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await WorktreeRepository(session).page(params.offset, params.limit)
    items = [
        WorktreeRead(
            id=w.id,
            repo_id=w.repo_id,
            repo=r.full,
            branch=w.branch,
            base_commit_sha=w.base_commit_sha,
            changes=len(w.changes or {}),
            stashed=len(w.stash or {}),
            updated_at=w.updated_at,
        )
        for w, r in rows
    ]
    return Page.of(items, total, params)


@router.get("/worktrees/{worktree_id}/log")
async def worktree_log(worktree_id: int, limit: int = 50):
    async with SessionLocal() as session:
        rows = await WorktreeRepository(session).logs(worktree_id, min(limit, 200))
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "sha": r.sha,
            "previous_sha": r.previous_sha,
            "user_id": r.user_id,
            "message": r.message,
            "created_at": r.created_at,
        }
        for r in rows
    ]
