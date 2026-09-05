import logging

from unsafie import telemetry
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import WorktreeRepository
from unsafie.github import merge
from unsafie.github.errors import Conflict, GithubError, NotFound
from unsafie.github.vfs import Overlay, encode
from unsafie.github.workspace import Session, author_for, ensure_worktree, load_tree, lock_for, save
from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)


async def _tree_entries(state: Session) -> list[dict]:
    entries: list[dict] = []
    for path in state.overlay.paths:
        entry = state.overlay.entry(path)
        if entry is None:
            continue
        if entry.deleted:
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        else:
            sha = await state.client.create_blob(entry.data)
            entries.append({"path": path, "mode": entry.mode, "type": "blob", "sha": sha})
    return entries


async def _remote_files(state: Session, base_tree: str, head_tree: str) -> tuple[dict, dict]:
    base = await state.client.tree(base_tree)
    head = await state.client.tree(head_tree)
    base_map = {e["path"]: e["sha"] for e in base.get("tree", []) if e.get("type") == "blob"}
    head_map = {e["path"]: e["sha"] for e in head.get("tree", []) if e.get("type") == "blob"}
    return base_map, head_map


@telemetry.traced("github.rebase")
async def _rebase(state: Session, remote_sha: str) -> merge.Result:
    telemetry.annotate(
        **{
            attrs.GH_REPO: state.repo.full,
            attrs.GH_BRANCH: state.branch,
            attrs.GH_SHA: remote_sha[:7],
        }
    )
    worktree = await ensure_worktree(state)
    remote_commit = await state.client.commit(remote_sha)
    base_map, head_map = await _remote_files(
        state, worktree.base_tree_sha, remote_commit["tree"]["sha"]
    )
    ours: dict[str, bytes | None] = {}
    for path in state.overlay.paths:
        entry = state.overlay.entry(path)
        ours[path] = None if entry is None or entry.deleted else entry.data
    touched = set(ours)
    blobs = await state.client.blobs(
        [sha for path in touched for sha in (base_map.get(path), head_map.get(path)) if sha]
    )
    theirs: dict[str, bytes | None] = {}
    for path in touched:
        if base_map.get(path) != head_map.get(path):
            theirs[path] = blobs.get(head_map[path]) if path in head_map else None
    base_files: dict[str, bytes | None] = {}
    for path in touched:
        base_files[path] = blobs.get(base_map[path]) if path in base_map else None
    result = merge.rebase(base_files, ours, theirs)
    state.overlay.clear()
    for path, data in result.merged.items():
        if data is None:
            state.overlay.delete(path)
        else:
            state.overlay.changes[path] = {"content": encode(data), "mode": "100644"}
    async with SessionLocal() as session:
        await WorktreeRepository(session).save(
            worktree.id,
            changes=state.overlay.to_json(),
            base_commit_sha=remote_sha,
            base_tree_sha=remote_commit["tree"]["sha"],
        )
    worktree.base_commit_sha = remote_sha
    worktree.base_tree_sha = remote_commit["tree"]["sha"]
    return result


@telemetry.traced("github.commit")
async def commit(state: Session, message: str, user_id: int) -> dict:
    telemetry.annotate(
        **{
            attrs.GH_REPO: state.repo.full,
            attrs.GH_BRANCH: state.branch,
            attrs.USER_ID: user_id,
            attrs.GH_FILES: len(state.overlay),
        }
    )
    if not state.dirty:
        raise GithubError("nothing to commit: the worktree is clean")
    async with lock_for(state.repo.id, state.branch):
        worktree = await ensure_worktree(state)
        remote = await state.client.ref_sha(state.branch)
        if remote is None:
            raise NotFound(f"branch '{state.branch}' has disappeared from the remote")
        rebased: merge.Result | None = None
        if remote != worktree.base_commit_sha:
            async with SessionLocal() as session:
                known = await WorktreeRepository(session).known_sha(worktree.id, remote)
            logger.info(
                "%s remote moved %s -> %s, rebasing",
                state.label,
                worktree.base_commit_sha[:7],
                remote[:7],
            )
            rebased = await _rebase(state, remote)
            if rebased.conflicts and not known:
                await save(state)
                raise Conflict(
                    "conflicts with the remote branch in: "
                    + ", ".join(rebased.conflicts)
                    + ". Conflict markers are in the worktree; fix the files and commit again."
                )
        entries = await _tree_entries(state)
        if not entries:
            raise GithubError("nothing to commit after the rebase")
        tree_sha = await state.client.create_tree(entries, worktree.base_tree_sha)
        author = await author_for(user_id, state.repo)
        created = await state.client.create_commit(
            message, tree_sha, [worktree.base_commit_sha], author
        )
        await state.client.update_ref(state.branch, created["sha"])
        async with SessionLocal() as session:
            repo = WorktreeRepository(session)
            await repo.save(
                worktree.id,
                changes={},
                base_commit_sha=created["sha"],
                base_tree_sha=tree_sha,
                pending=None,
            )
            await repo.log(
                worktree.id, user_id, "commit", created["sha"], worktree.base_commit_sha, message
            )
        files = len(entries)
        state.overlay.clear()
        telemetry.annotate(
            **{
                attrs.GH_SHA: created["sha"][:7],
                attrs.GH_FILES: files,
                "unsafie.github.rebased": bool(rebased),
            }
        )
        logger.info("%s committed %s (%s files)", state.label, created["sha"][:7], files)
        return {
            "sha": created["sha"],
            "files": files,
            "rebased": bool(rebased),
            "conflicts": rebased.conflicts if rebased else [],
        }


@telemetry.traced("github.amend")
async def amend(state: Session, message: str | None, user_id: int) -> dict:
    telemetry.annotate(
        **{attrs.GH_REPO: state.repo.full, attrs.GH_BRANCH: state.branch, attrs.USER_ID: user_id}
    )
    async with lock_for(state.repo.id, state.branch):
        worktree = await ensure_worktree(state)
        head = await state.client.commit(worktree.base_commit_sha)
        if not head.get("parents"):
            raise GithubError("cannot amend the very first commit")
        async with SessionLocal() as session:
            if not await WorktreeRepository(session).known_sha(worktree.id, head["sha"]):
                raise GithubError(
                    "the head commit was not made from here; amending someone else's commit is not allowed"
                )
        parent = head["parents"][0]["sha"]
        parent_commit = await state.client.commit(parent)
        entries = await _tree_entries(state)
        tree_sha = (
            await state.client.create_tree(entries, head["tree"]["sha"])
            if entries
            else head["tree"]["sha"]
        )
        author = await author_for(user_id, state.repo)
        created = await state.client.create_commit(
            message or head["message"], tree_sha, [parent], author
        )
        await state.client.update_ref(state.branch, created["sha"], force=True)
        async with SessionLocal() as session:
            repo = WorktreeRepository(session)
            await repo.save(
                worktree.id, changes={}, base_commit_sha=created["sha"], base_tree_sha=tree_sha
            )
            await repo.log(
                worktree.id,
                user_id,
                "amend",
                created["sha"],
                head["sha"],
                message or head["message"],
            )
        state.overlay.clear()
        _ = parent_commit
        return {"sha": created["sha"], "replaced": head["sha"]}


async def revert(state: Session, paths: list[str] | None) -> list[str]:
    if paths:
        dropped = [p for p in paths if state.overlay.forget(p)]
    else:
        dropped = state.overlay.paths
        state.overlay.clear()
    await save(state)
    return dropped


async def stash(state: Session) -> int:
    worktree = await ensure_worktree(state)
    count = len(state.overlay)
    if not count:
        raise GithubError("nothing to stash")
    async with SessionLocal() as session:
        await WorktreeRepository(session).save(
            worktree.id, stash=state.overlay.to_json(), changes={}
        )
    state.overlay.clear()
    return count


async def unstash(state: Session) -> int:
    worktree = await ensure_worktree(state)
    if not worktree.stash:
        raise GithubError("the stash is empty")
    stashed = Overlay(worktree.stash)
    for path in stashed.paths:
        state.overlay.changes.setdefault(path, stashed.changes[path])
    async with SessionLocal() as session:
        await WorktreeRepository(session).save(
            worktree.id, changes=state.overlay.to_json(), stash=None
        )
    return len(stashed)


async def push_changes(state: Session, message: str, user_id: int) -> dict:
    _ = await load_tree(state)
    if len(state.overlay) > settings.github_max_changes:
        raise GithubError("too many changed files for one commit")
    return await commit(state, message, user_id)
