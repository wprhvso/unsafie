import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.gh.format import commit_line
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import WorktreeRepository
from unsafie.github import workspace
from unsafie.github.errors import GithubError
from unsafie.github.ops import branches
from unsafie.github.ops import commit as commit_ops

logger = logging.getLogger(__name__)

REPO_ARGS = dict(repo=str, branch=str)


@register(
    SERVER,
    "git_status",
    "State of the worktree: current branch, uncommitted changes, how far the remote branch has moved, "
    "what is in the stash.",
    schema([], **REPO_ARGS),
)
@guarded
async def git_status(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    worktree = await workspace.ensure_worktree(state)
    remote = await state.client.ref_sha(state.branch)
    lines = [f"{state.label} at `{worktree.base_commit_sha[:7]}`"]
    if remote and remote != worktree.base_commit_sha:
        lines.append(
            f"remote moved to `{remote[:7]}` — git_sync or commit (a rebase happens automatically)"
        )
    changes = state.overlay.summary()
    lines.append(f"{len(changes)} uncommitted change(s)" if changes else "worktree is clean")
    lines.extend(changes[:50])
    if len(changes) > 50:
        lines.append(f"…and {len(changes) - 50} more")
    if worktree.stash:
        lines.append(f"stash: {len(worktree.stash)} file(s)")
    return text("\n".join(lines))


@register(
    SERVER,
    "git_diff",
    "What has changed in the worktree relative to the last commit: a unified diff. path — limit to "
    "one file. Binary files are shown as a line.",
    schema([], path=str, **REPO_ARGS),
)
@guarded
async def git_diff(ctx: ToolContext, args: dict) -> dict:
    import difflib

    from unsafie.mime import decode_text

    state = await session_for(ctx, args)
    tree = await workspace.load_tree(state)
    paths = [args["path"]] if args.get("path") else state.overlay.paths
    if not paths:
        return text("worktree is clean")
    shas = {path: tree.blob_sha(path) for path in paths}
    committed = await state.client.blobs(sha for sha in shas.values() if sha)
    out: list[str] = []
    for path in paths:
        entry = state.overlay.entry(path)
        if entry is None:
            continue
        sha = shas.get(path)
        before = committed.get(sha, b"") if sha else b""
        after = b"" if entry.deleted else entry.data
        old = decode_text(before)
        new = decode_text(after)
        if old is None or new is None:
            out.append(f"--- {path}\n+++ {path}\n(binary file changed)")
            continue
        diff = difflib.unified_diff(
            old[0].splitlines(keepends=True),
            new[0].splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        out.append("".join(diff).rstrip())
    body = "\n\n".join(x for x in out if x)
    if len(body) > 60_000:
        body = body[:60_000] + "\n…(truncated, ask for one path)"
    return text(body or "no textual differences")


@register(
    SERVER,
    "git_commit",
    "Commit the worktree changes and push them to the branch. If the remote branch has moved, a "
    "three-way rebase happens automatically; on conflicts the files are left with markers and the "
    "commit is refused.",
    schema(["message"], message=str, **REPO_ARGS),
)
@guarded
async def git_commit(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    result = await commit_ops.commit(state, args["message"], ctx.user_id)
    note = " (rebased onto the remote)" if result["rebased"] else ""
    return text(
        f"committed `{result['sha'][:7]}` — {result['files']} file(s) in {state.label}{note}"
    )


@register(
    SERVER,
    "git_amend",
    "Amend the last commit made from here: add worktree changes and/or change the message. "
    "Force-pushes the branch. Someone else's commit cannot be amended.",
    schema([], message=str, **REPO_ARGS),
)
@guarded
async def git_amend(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    result = await commit_ops.amend(state, args.get("message"), ctx.user_id)
    return text(f"amended: `{result['replaced'][:7]}` → `{result['sha'][:7]}` in {state.label}")


@register(
    SERVER,
    "git_revert",
    "Drop uncommitted changes: paths — comma-separated list, or everything when omitted.",
    schema([], paths=str, **REPO_ARGS),
)
@guarded
async def git_revert(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    raw = args.get("paths")
    paths = [p.strip() for p in raw.split(",") if p.strip()] if raw else None
    dropped = await commit_ops.revert(state, paths)
    return text(f"dropped {len(dropped)} change(s) in {state.label}: " + ", ".join(dropped[:20]))


@register(
    SERVER,
    "git_stash",
    "Put uncommitted changes aside (pop=true — bring them back). Useful before switching branches.",
    schema([], pop=bool, **REPO_ARGS),
)
@guarded
async def git_stash(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    if args.get("pop"):
        n = await commit_ops.unstash(state)
        return text(f"restored {n} file(s) from the stash in {state.label}")
    n = await commit_ops.stash(state)
    return text(f"stashed {n} file(s) in {state.label}")


@register(
    SERVER,
    "git_branch",
    "Branches: without arguments — a list; create — create a new one (from source or the default "
    "branch); delete — delete; switch — switch the worktree (requires a clean worktree).",
    schema([], create=str, source=str, delete=str, switch=str, repo=str, branch=str),
)
@guarded
async def git_branch(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    if name := args.get("create"):
        result = await branches.create_branch(state, name, args.get("source"))
        return text(
            f"branch `{result['branch']}` created from `{result['from']}` at {result['sha'][:7]}"
        )
    if name := args.get("delete"):
        await branches.delete_branch(state, name)
        return text(f"branch `{name}` deleted in {state.repo.full}")
    if name := args.get("switch"):
        await branches.switch(state, name)
        return text(f"switched to `{name}` in {state.repo.full}")
    items = await state.client.branches()
    default = await workspace.default_branch(state.repo, state.client)
    lines = [
        f"{'*' if b['name'] == state.branch else ' '} {b['name']}"
        + (" (default)" if b["name"] == default else "")
        + (" 🔒" if b.get("protected") else "")
        for b in items
    ]
    return text(f"{state.repo.full} branches:\n" + "\n".join(lines))


@register(
    SERVER,
    "git_sync",
    "Pull the remote branch state into the worktree. Uncommitted changes are rebased on top; "
    "conflicts are reported.",
    schema([], **REPO_ARGS),
)
@guarded
async def git_sync(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    result = await branches.sync(state)
    if not result["changed"]:
        return text(f"{state.label} is already up to date at `{result['sha'][:7]}`")
    lines = [f"{state.label} synced to `{result['sha'][:7]}`"]
    if result.get("conflicts"):
        lines.append("conflicts (markers left in the files): " + ", ".join(result["conflicts"]))
    if result.get("taken_remote"):
        lines.append("taken from the remote: " + ", ".join(result["taken_remote"][:20]))
    return text("\n".join(lines))


@register(
    SERVER,
    "git_log",
    "Commit history of the branch: limit (default 20), path — only commits touching a file.",
    schema([], limit=int, path=str, **REPO_ARGS),
)
@guarded
async def git_log(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    items = await state.client.commits(
        state.branch, args.get("path"), max(1, min(int(args.get("limit") or 20), 100))
    )
    if not items:
        return text("no commits")
    return text(f"{state.label}:\n" + "\n".join(commit_line(c) for c in items))


@register(
    SERVER,
    "git_show",
    "One commit: message, author, changed files with a diff. sha — the commit hash (the branch head "
    "by default).",
    schema([], sha=str, **REPO_ARGS),
)
@guarded
async def git_show(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    sha = args.get("sha")
    if not sha:
        sha = await state.client.ref_sha(state.branch)
        if sha is None:
            raise GithubError(f"branch {state.branch} not found")
    data = await state.client.compare(f"{sha}^", sha)
    info = await state.client.commit(sha)
    lines = [
        f"`{sha[:7]}` {info.get('message', '').strip()}",
        f"author: {(info.get('author') or {}).get('name')} <{(info.get('author') or {}).get('email')}>",
        f"{len(data.get('files') or [])} file(s) changed",
    ]
    for f in (data.get("files") or [])[:20]:
        lines.append(
            f"  {f.get('status')} {f.get('filename')} (+{f.get('additions')}/-{f.get('deletions')})"
        )
    patches = "\n\n".join(
        f"--- {f['filename']}\n{f.get('patch', '')}"
        for f in (data.get("files") or [])[:10]
        if f.get("patch")
    )
    body = "\n".join(lines) + ("\n\n" + patches if patches else "")
    return text(body[:60_000])


@register(
    SERVER,
    "git_history",
    "What has been done from this chat in the repository worktree: commits, amends, reverts.",
    schema([], limit=int, **REPO_ARGS),
)
@guarded
async def git_history(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    worktree = await workspace.ensure_worktree(state)
    async with SessionLocal() as session:
        rows = await WorktreeRepository(session).logs(
            worktree.id, max(1, min(int(args.get("limit") or 20), 100))
        )
    if not rows:
        return text("nothing has been done here yet")
    lines = [
        f"{r.created_at:%Y-%m-%d %H:%M} {r.kind} `{r.sha[:7]}` {r.message.splitlines()[0] if r.message else ''}"
        for r in rows
    ]
    return text(f"{state.label}:\n" + "\n".join(lines))
