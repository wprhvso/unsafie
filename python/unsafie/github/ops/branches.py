import logging

from unsafie.database import SessionLocal
from unsafie.database.repositories.github import WorktreeRepository
from unsafie.github.errors import Conflict, GithubError, NotFound
from unsafie.github.workspace import Session, default_branch, ensure_worktree, lock_for

logger = logging.getLogger(__name__)


async def create_branch(state: Session, name: str, source: str | None) -> dict:
    base = source or await default_branch(state.repo, state.client)
    sha = await state.client.ref_sha(base)
    if sha is None:
        msg = f"source branch '{base}' does not exist"
        raise NotFound(msg)
    if await state.client.ref_sha(name) is not None:
        msg = f"branch '{name}' already exists"
        raise Conflict(msg)
    await state.client.create_ref(name, sha)
    logger.info("%s branch %s created from %s", state.repo.full, name, base)
    return {"branch": name, "from": base, "sha": sha}


async def delete_branch(state: Session, name: str) -> None:
    if name == await default_branch(state.repo, state.client):
        msg = "the default branch cannot be deleted"
        raise GithubError(msg)
    await state.client.delete_ref(name)
    async with SessionLocal() as session:
        await WorktreeRepository(session).delete(state.repo.id, name)


async def switch(state: Session, branch: str) -> dict:
    if state.dirty:
        msg = (
            f"{len(state.overlay)} uncommitted change(s) in {state.branch}: "
            "commit them (git_commit), stash them (git_stash) or drop them (git_revert)"
        )
        raise Conflict(
            msg,
        )
    if await state.client.ref_sha(branch) is None:
        msg = f"branch '{branch}' does not exist; create it with git_branch"
        raise NotFound(msg)
    state.branch = branch
    state.worktree = None
    state.tree = None
    await ensure_worktree(state)
    return {"branch": branch}


async def sync(state: Session) -> dict:
    async with lock_for(state.repo.id, state.branch):
        worktree = await ensure_worktree(state)
        remote = await state.client.ref_sha(state.branch)
        if remote is None:
            msg = f"branch '{state.branch}' has disappeared from the remote"
            raise NotFound(msg)
        if remote == worktree.base_commit_sha:
            return {"changed": False, "sha": remote}
        if state.dirty:
            from unsafie.github.ops.commit import rebase_branch

            result = await rebase_branch(state, remote)
            return {
                "changed": True,
                "sha": remote,
                "conflicts": result.conflicts,
                "taken_remote": result.taken_remote,
            }
        commit = await state.client.commit(remote)
        async with SessionLocal() as session:
            await WorktreeRepository(session).save(
                worktree.id, base_commit_sha=remote, base_tree_sha=commit["tree"]["sha"],
            )
        state.tree = None
        return {"changed": True, "sha": remote, "conflicts": []}
