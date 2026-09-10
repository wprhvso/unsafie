import asyncio
import logging
from dataclasses import dataclass

from unsafie import telemetry
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import WorktreeRepository
from unsafie.github import cache, merge
from unsafie.github.errors import Conflict, GithubError, NotFound
from unsafie.github.vfs import Entry, Overlay, encode
from unsafie.github.workspace import Session, author_for, ensure_worktree, load_tree, lock_for, save
from unsafie.mime import is_text
from unsafie.settings import settings
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)


@dataclass
class Upload:
    entries: list[dict]
    blobs: int
    inlined: int
    unchanged: int
    size: int


def _inlineable(entry: Entry, data: bytes) -> bool:
    if entry.mode != "100644" or len(data) > settings.github_inline_bytes:
        return False
    if not is_text(data):
        return False
    try:
        data.decode()
    except UnicodeDecodeError:
        return False
    return True


async def _tree_entries(state: Session) -> Upload:
    base = await load_tree(state)
    entries: list[dict] = []
    pending: list[tuple[str, str, bytes]] = []
    inlined = unchanged = size = inlined_bytes = 0
    for path in state.overlay.paths:
        entry = state.overlay.entry(path)
        if entry is None:
            continue
        if entry.deleted:
            if base.blob_sha(path) is None and not base.truncated:
                unchanged += 1
                continue
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            continue
        data = entry.data
        if base.blob_sha(path) == cache.git_sha(data) and base.mode(path) == entry.mode:
            unchanged += 1
            continue
        size += len(data)
        if inlined_bytes + len(data) <= settings.github_inline_total_bytes and _inlineable(
            entry, data,
        ):
            entries.append(
                {"path": path, "mode": entry.mode, "type": "blob", "content": data.decode()},
            )
            inlined += 1
            inlined_bytes += len(data)
        else:
            pending.append((path, entry.mode, data))
    if pending:
        shas = await state.client.create_blobs([data for _, _, data in pending])
        for (path, mode, _), sha in zip(pending, shas, strict=True):
            entries.append({"path": path, "mode": mode, "type": "blob", "sha": sha})
    entries.sort(key=lambda item: item["path"])
    return Upload(entries, len(pending), inlined, unchanged, size)


async def _remote_files(state: Session, base_tree: str, head_tree: str) -> tuple[dict, dict]:
    base, head = await asyncio.gather(state.client.tree(base_tree), state.client.tree(head_tree))
    base_map = {e["path"]: e["sha"] for e in base.get("tree", []) if e.get("type") == "blob"}
    head_map = {e["path"]: e["sha"] for e in head.get("tree", []) if e.get("type") == "blob"}
    return base_map, head_map


@telemetry.traced("github.rebase")
async def rebase_branch(state: Session, remote_sha: str) -> merge.Result:
    telemetry.annotate(
        **{
            attrs.GH_REPO: state.repo.full,
            attrs.GH_BRANCH: state.branch,
            attrs.GH_SHA: remote_sha[:7],
        },
    )
    worktree = await ensure_worktree(state)
    remote_commit = await state.client.commit(remote_sha)
    base_map, head_map = await _remote_files(
        state, worktree.base_tree_sha, remote_commit["tree"]["sha"],
    )
    ours: dict[str, bytes | None] = {}
    for path in state.overlay.paths:
        entry = state.overlay.entry(path)
        ours[path] = None if entry is None or entry.deleted else entry.data
    touched = set(ours)
    blobs = await state.client.blobs(
        [sha for path in touched for sha in (base_map.get(path), head_map.get(path)) if sha],
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
    state.tree = None
    return result


@telemetry.traced("github.commit")
async def commit(state: Session, message: str, user_id: int) -> dict:
    telemetry.annotate(
        **{
            attrs.GH_REPO: state.repo.full,
            attrs.GH_BRANCH: state.branch,
            attrs.USER_ID: user_id,
            attrs.GH_FILES: len(state.overlay),
        },
    )
    if not state.dirty:
        msg = "nothing to commit: the worktree is clean"
        raise GithubError(msg)
    async with lock_for(state.repo.id, state.branch):
        worktree, remote = await asyncio.gather(
            ensure_worktree(state), state.client.ref_sha(state.branch),
        )
        if remote is None:
            msg = f"branch '{state.branch}' has disappeared from the remote"
            raise NotFound(msg)
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
            rebased = await rebase_branch(state, remote)
            if rebased.conflicts and not known:
                await save(state)
                raise Conflict(
                    "conflicts with the remote branch in: "
                    + ", ".join(rebased.conflicts)
                    + ". Conflict markers are in the worktree; fix the files and commit again.",
                )
        upload = await _tree_entries(state)
        if not upload.entries:
            state.overlay.clear()
            await save(state)
            msg = "nothing to commit: the worktree matches the branch"
            raise GithubError(msg)
        tree_sha = await state.client.create_tree(upload.entries, worktree.base_tree_sha)
        author = await author_for(user_id, state.repo)
        created = await state.client.create_commit(
            message, tree_sha, [worktree.base_commit_sha], author,
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
                worktree.id, user_id, "commit", created["sha"], worktree.base_commit_sha, message,
            )
        files = len(upload.entries)
        state.overlay.clear()
        state.tree = None
        telemetry.annotate(
            **{
                attrs.GH_SHA: created["sha"][:7],
                attrs.GH_FILES: files,
                attrs.GH_BLOBS: upload.blobs,
                attrs.GH_INLINE: upload.inlined,
                attrs.GH_UNCHANGED: upload.unchanged,
                attrs.GH_BYTES: upload.size,
                "unsafie.github.rebased": bool(rebased),
            },
        )
        logger.info(
            "%s committed %s (%s files, %s blobs uploaded, %s inlined, %s unchanged)",
            state.label,
            created["sha"][:7],
            files,
            upload.blobs,
            upload.inlined,
            upload.unchanged,
        )
        return {
            "sha": created["sha"],
            "files": files,
            "rebased": bool(rebased),
            "conflicts": rebased.conflicts if rebased else [],
        }


@telemetry.traced("github.amend")
async def amend(state: Session, message: str | None, user_id: int) -> dict:
    telemetry.annotate(
        **{attrs.GH_REPO: state.repo.full, attrs.GH_BRANCH: state.branch, attrs.USER_ID: user_id},
    )
    async with lock_for(state.repo.id, state.branch):
        worktree = await ensure_worktree(state)
        head = await state.client.commit(worktree.base_commit_sha)
        if not head.get("parents"):
            msg = "cannot amend the very first commit"
            raise GithubError(msg)
        async with SessionLocal() as session:
            if not await WorktreeRepository(session).known_sha(worktree.id, head["sha"]):
                msg = "the head commit was not made from here; amending someone else's commit is not allowed"
                raise GithubError(
                    msg,
                )
        parent = head["parents"][0]["sha"]
        if head["tree"]["sha"] != worktree.base_tree_sha:
            worktree.base_tree_sha = head["tree"]["sha"]
            state.tree = None
        upload = await _tree_entries(state)
        tree_sha = (
            await state.client.create_tree(upload.entries, head["tree"]["sha"])
            if upload.entries
            else head["tree"]["sha"]
        )
        author = await author_for(user_id, state.repo)
        created = await state.client.create_commit(
            message or head["message"], tree_sha, [parent], author,
        )
        await state.client.update_ref(state.branch, created["sha"], force=True)
        async with SessionLocal() as session:
            repo = WorktreeRepository(session)
            await repo.save(
                worktree.id, changes={}, base_commit_sha=created["sha"], base_tree_sha=tree_sha,
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
        state.tree = None
        telemetry.annotate(
            **{
                attrs.GH_SHA: created["sha"][:7],
                attrs.GH_FILES: len(upload.entries),
                attrs.GH_BLOBS: upload.blobs,
                attrs.GH_INLINE: upload.inlined,
                attrs.GH_UNCHANGED: upload.unchanged,
                attrs.GH_BYTES: upload.size,
            },
        )
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
        msg = "nothing to stash"
        raise GithubError(msg)
    async with SessionLocal() as session:
        await WorktreeRepository(session).save(
            worktree.id, stash=state.overlay.to_json(), changes={},
        )
    state.overlay.clear()
    return count


async def unstash(state: Session) -> int:
    worktree = await ensure_worktree(state)
    if not worktree.stash:
        msg = "the stash is empty"
        raise GithubError(msg)
    stashed = Overlay(worktree.stash)
    for path in stashed.paths:
        state.overlay.changes.setdefault(path, stashed.changes[path])
    async with SessionLocal() as session:
        await WorktreeRepository(session).save(
            worktree.id, changes=state.overlay.to_json(), stash=None,
        )
    return len(stashed)


async def push_changes(state: Session, message: str, user_id: int) -> dict:
    _ = await load_tree(state)
    if len(state.overlay) > settings.github_max_changes:
        msg = "too many changed files for one commit"
        raise GithubError(msg)
    return await commit(state, message, user_id)
