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
        raise NotFound(f"source branch '{base}' does not exist")
    if await state.client.ref_sha(name) is not None:
        raise Conflict(f"branch '{name}' already exists")
    await state.client.create_ref(name, sha)
    logger.info("%s branch %s created from %s", state.repo.full, name, base)
    return {"branch": name, "from": base, "sha": sha}


async def delete_branch(state: Session, name: str) -> None:
    if name == await default_branch(state.repo, state.client):
        raise GithubError("the default branch cannot be deleted")
    await state.client.delete_ref(name)
    async with SessionLocal() as session:
        await WorktreeRepository(session).delete(state.repo.id, name)


async def switch(state: Session, branch: str) -> dict:
    if state.dirty:
        raise Conflict(
            f"{len(state.overlay)} uncommitted change(s) in {state.branch}: "
            "commit them (git_commit), stash them (git_stash) or drop them (git_revert)"
        )
    if await state.client.ref_sha(branch) is None:
        raise NotFound(f"branch '{branch}' does not exist; create it with git_branch")
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
            raise NotFound(f"branch '{state.branch}' has disappeared from the remote")
        if remote == worktree.base_commit_sha:
            return {"changed": False, "sha": remote}
        if state.dirty:
            from unsafie.github.ops.commit import _rebase

            result = await _rebase(state, remote)
            return {
                "changed": True,
                "sha": remote,
                "conflicts": result.conflicts,
                "taken_remote": result.taken_remote,
            }
        commit = await state.client.commit(remote)
        async with SessionLocal() as session:
            await WorktreeRepository(session).save(
                worktree.id, base_commit_sha=remote, base_tree_sha=commit["tree"]["sha"]
            )
        state.tree = None
        return {"changed": True, "sha": remote, "conflicts": []}
