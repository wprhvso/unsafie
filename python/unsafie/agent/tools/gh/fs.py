import logging
import posixpath

from unsafie.agent.tools.base import ToolContext, error, guarded, schema, text
from unsafie.agent.tools.files import deliver
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.gh.format import tree_listing
from unsafie.agent.tools.registry import register
from unsafie.github import workspace
from unsafie.github.errors import NotFound
from unsafie.github.vfs import normalize
from unsafie.mime import (
    decode_text,
    human_size,
    image_problem,
    image_result,
    number_lines,
    sniff_mime,
)

logger = logging.getLogger(__name__)

READ_LIMIT = 400_000
SEARCH_LIMIT = 400
GREP_MATCHES = 200
READ_BATCH = 200

REPO_ARGS = dict(repo=str, branch=str)


@register(
    SERVER,
    "fs_read",
    "Read a file from a repository with line numbers. path — relative to the repository root. "
    "start_line/end_line — a range. Uncommitted changes from the worktree are included.",
    schema(["path"], path=str, start_line=int, end_line=int, **REPO_ARGS),
)
@guarded
async def fs_read(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    path = normalize(args["path"])
    data = await workspace.read(state, path)
    if data is None:
        raise NotFound(f"{path} does not exist in {state.label}")
    decoded = decode_text(data)
    if decoded is None:
        mime = sniff_mime(data, path)
        hint = (
            " Use fs_view to look at it."
            if mime.startswith("image/")
            else " Use fs_download to send it."
        )
        return error(f"{path} is binary ({mime}, {human_size(len(data))}).{hint}")
    body, enc = decoded
    numbered, total = number_lines(body, args.get("start_line"), args.get("end_line"), READ_LIMIT)
    marker = " *modified*" if path in state.overlay else ""
    head = f"{state.label}:{path}{marker} [{total} lines{'' if enc == 'utf-8' else ', ' + enc}]\n"
    return text(head + (numbered or "<empty file>"))


@register(
    SERVER,
    "fs_write",
    "Write a file into the worktree (not committed yet — use git_commit). content — the full new "
    "text of the file. Existing files are overwritten. Use fs_edit for a partial change.",
    schema(["path", "content"], path=str, content=str, **REPO_ARGS),
)
@guarded
async def fs_write(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    path = normalize(args["path"])
    state.overlay.write(path, args["content"].encode())
    await workspace.save(state)
    return text(f"written {path} ({human_size(len(args['content'].encode()))}) into {state.label}")


@register(
    SERVER,
    "fs_edit",
    "Replace a fragment in a file: old must occur exactly once (or pass all=true to replace every "
    "occurrence). Empty new deletes the fragment. Cheaper and safer than rewriting the whole file.",
    schema(["path", "old", "new"], path=str, old=str, new=str, all=bool, **REPO_ARGS),
)
@guarded
async def fs_edit(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    path = normalize(args["path"])
    data = await workspace.read(state, path)
    if data is None:
        raise NotFound(f"{path} does not exist in {state.label}")
    decoded = decode_text(data)
    if decoded is None:
        return error(f"{path} is binary, cannot edit as text")
    body = decoded[0]
    old, new = args["old"], args.get("new") or ""
    count = body.count(old)
    if count == 0:
        return error(f"the fragment is not found in {path}; check whitespace and indentation")
    if count > 1 and not args.get("all"):
        return error(
            f"the fragment occurs {count} times in {path}; make it unique or pass all=true"
        )
    updated = body.replace(old, new) if args.get("all") else body.replace(old, new, 1)
    state.overlay.write(path, updated.encode())
    await workspace.save(state)
    return text(
        f"edited {path} ({count if args.get('all') else 1} replacement(s)) in {state.label}"
    )


@register(
    SERVER,
    "fs_delete",
    "Delete a file from the worktree (applied on the next git_commit).",
    schema(["path"], path=str, **REPO_ARGS),
)
@guarded
async def fs_delete(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    path = normalize(args["path"])
    tree = await workspace.load_tree(state)
    if not tree.exists(path):
        raise NotFound(f"{path} does not exist in {state.label}")
    state.overlay.delete(path)
    await workspace.save(state)
    return text(f"deleted {path} from {state.label}")


@register(
    SERVER,
    "fs_move",
    "Move or rename a file inside the worktree.",
    schema(["path", "to"], path=str, to=str, **REPO_ARGS),
)
@guarded
async def fs_move(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    src, dst = normalize(args["path"]), normalize(args["to"])
    data = await workspace.read(state, src)
    if data is None:
        raise NotFound(f"{src} does not exist in {state.label}")
    state.overlay.write(dst, data)
    state.overlay.delete(src)
    await workspace.save(state)
    return text(f"moved {src} → {dst} in {state.label}")


@register(
    SERVER,
    "fs_list",
    "List a directory in the repository: subdirectories and files. path — a directory (root by "
    "default). pattern — a glob over the whole tree instead (e.g. '**/*.py', 'src/**').",
    schema([], path=str, pattern=str, **REPO_ARGS),
)
@guarded
async def fs_list(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    tree = await workspace.load_tree(state)
    if pattern := args.get("pattern"):
        paths = tree.paths(pattern)
        if not paths:
            return text(f"nothing matches '{pattern}' in {state.label}")
        body = "\n".join(paths[:SEARCH_LIMIT])
        if len(paths) > SEARCH_LIMIT:
            body += f"\n…and {len(paths) - SEARCH_LIMIT} more"
        return text(f"{state.label} — {len(paths)} file(s):\n{body}")
    prefix = args.get("path") or ""
    dirs, files = tree.listing(prefix)
    if not dirs and not files:
        raise NotFound(f"{prefix or '/'} is empty or does not exist in {state.label}")
    return text(f"{state.label}:{prefix or '/'}\n" + tree_listing(dirs, files))


@register(
    SERVER,
    "fs_search",
    "Search text inside repository files. query — a substring (regex=true for a regular expression). "
    "pattern — restrict to a glob of paths. Searches the worktree tree; large repositories are "
    "capped, narrow with pattern. Use gh_code_search for search across all of GitHub.",
    schema(["query"], query=str, pattern=str, regex=bool, ignore_case=bool, limit=int, **REPO_ARGS),
)
@guarded
async def fs_search(ctx: ToolContext, args: dict) -> dict:
    import re

    state = await session_for(ctx, args)
    tree = await workspace.load_tree(state)
    paths = tree.paths(args.get("pattern"))
    if len(paths) > SEARCH_LIMIT:
        return error(
            f"{len(paths)} files match; the limit is {SEARCH_LIMIT}. Narrow it with pattern "
            "(e.g. '**/*.py' or 'src/**')."
        )
    flags = re.IGNORECASE if args.get("ignore_case") else 0
    try:
        needle = re.compile(args["query"] if args.get("regex") else re.escape(args["query"]), flags)
    except re.error as e:
        return error(f"bad regular expression: {e}")
    limit = max(1, min(int(args.get("limit") or 50), GREP_MATCHES))
    hits: list[str] = []
    scanned = 0
    for start in range(0, len(paths), READ_BATCH):
        if len(hits) >= limit:
            break
        batch = paths[start : start + READ_BATCH]
        files = await workspace.read_many(state, batch)
        for path in batch:
            data = files.get(path)
            if data is None:
                continue
            decoded = decode_text(data)
            if decoded is None:
                continue
            scanned += 1
            for n, line in enumerate(decoded[0].splitlines(), 1):
                if needle.search(line):
                    hits.append(f"{path}:{n}: {line.strip()[:200]}")
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit:
                break
    if not hits:
        return text(f"nothing found in {scanned} file(s) of {state.label}")
    return text(f"{len(hits)} hit(s) in {scanned} scanned file(s):\n" + "\n".join(hits))


@register(
    SERVER,
    "fs_view",
    "Look at an image stored in the repository (jpeg/png/gif/webp).",
    schema(["path"], path=str, **REPO_ARGS),
)
@guarded
async def fs_view(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    path = normalize(args["path"])
    data = await workspace.read(state, path)
    if data is None:
        raise NotFound(f"{path} does not exist in {state.label}")
    mime = sniff_mime(data, path)
    if problem := image_problem(data, mime):
        return error(f"cannot view {path}: {problem}")
    return image_result(data, mime, f"{path} ({mime}, {human_size(len(data))})")


@register(
    SERVER,
    "fs_download",
    "Send a file from the repository to the user in the chat.",
    schema(["path"], path=str, caption=str, **REPO_ARGS),
    replies=True,
)
@guarded
async def fs_download(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    path = normalize(args["path"])
    data = await workspace.read(state, path)
    if data is None:
        raise NotFound(f"{path} does not exist in {state.label}")
    return await deliver(ctx, data, posixpath.basename(path), caption=args.get("caption"))


@register(
    SERVER,
    "fs_upload",
    "Put a file received in Telegram (file_id) into the repository worktree at path.",
    schema(["file_id", "path"], file_id=str, path=str, **REPO_ARGS),
)
@guarded
async def fs_upload(ctx: ToolContext, args: dict) -> dict:
    from unsafie.telegram.retry import download

    state = await session_for(ctx, args)
    path = normalize(args["path"])
    data = await download(ctx.bot, args["file_id"], f"{ctx.prefix} download")
    state.overlay.write(path, data)
    await workspace.save(state)
    return text(f"stored {path} ({human_size(len(data))}) in {state.label}")


@register(
    SERVER,
    "gh_code_search",
    "Search code across all of GitHub (not only connected repositories) using the user's account. "
    "query uses GitHub search syntax: 'repo:owner/name path:*.py foo', 'org:acme lang:go bar'. "
    "Requires a connected account.",
    schema(["query"], query=str, limit=int, account=str),
)
@guarded
async def gh_code_search(ctx: ToolContext, args: dict) -> dict:
    from unsafie.agent.tools.gh.context import user_client

    client = await user_client(ctx.user_id, args.get("account"))
    limit = max(1, min(int(args.get("limit") or 20), 50))
    items = await client.search_code(args["query"], limit)
    if not items:
        return text("nothing found")
    lines = [
        f"{it.get('repository', {}).get('full_name')}:{it.get('path')} — {it.get('html_url')}"
        for it in items
    ]
    return text(f"{len(items)} hit(s):\n" + "\n".join(lines))
