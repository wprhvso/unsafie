import json
import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, user_client
from unsafie.agent.tools.registry import register
from unsafie.github.errors import GithubError

logger = logging.getLogger(__name__)


def _files(raw: str | None, filename: str | None, content: str | None) -> dict:
    if raw:
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise GithubError(f"files is not JSON: {e}") from None
        if not isinstance(data, dict):
            raise GithubError('files must be a JSON object {"name.py": "content"}')
        return {k: ({"content": v} if isinstance(v, str) else v) for k, v in data.items()}
    if filename and content is not None:
        return {filename: {"content": content}}
    raise GithubError("files, or filename + content, is required")


@register(
    SERVER,
    "gist_list",
    "The user's gists. gist_id — show one with its content.",
    schema([], gist_id=str, limit=int, account=str),
)
@guarded
async def gist_list(ctx: ToolContext, args: dict) -> dict:
    client = await user_client(ctx.user_id, args.get("account"))
    if gist_id := args.get("gist_id"):
        gist = await client.gist(gist_id)
        lines = [f"{gist.get('description') or '(no description)'} — {gist.get('html_url')}"]
        for name, item in (gist.get("files") or {}).items():
            lines.append(
                f"\n--- {name} ({item.get('size')} bytes) ---\n{item.get('content') or ''}"
            )
        return text("\n".join(lines)[:60_000])
    items = await client.gists(max(1, min(int(args.get("limit") or 20), 50)))
    if not items:
        return text("no gists")
    lines = [
        f"{'🔓' if g.get('public') else '🔒'} {g['id']} · {', '.join(g.get('files') or {})} · "
        f"{g.get('description') or ''}"
        for g in items
    ]
    return text("\n".join(lines))


@register(
    SERVER,
    "gist_create",
    'Create a gist: files — a JSON object {"name.py": "content"}, or filename + content. '
    "description, public (false by default — a secret gist).",
    schema([], files=str, filename=str, content=str, description=str, public=bool, account=str),
)
@guarded
async def gist_create(ctx: ToolContext, args: dict) -> dict:
    client = await user_client(ctx.user_id, args.get("account"))
    files = _files(args.get("files"), args.get("filename"), args.get("content"))
    gist = await client.create_gist(files, args.get("description") or "", bool(args.get("public")))
    return text(f"gist created: {gist['html_url']}")


@register(
    SERVER,
    "gist_update",
    "Change a gist: gist_id + files (or filename + content); a null content deletes a file. "
    "delete=true removes the whole gist.",
    schema(
        ["gist_id"],
        gist_id=str,
        files=str,
        filename=str,
        content=str,
        description=str,
        delete=bool,
        account=str,
    ),
)
@guarded
async def gist_update(ctx: ToolContext, args: dict) -> dict:
    client = await user_client(ctx.user_id, args.get("account"))
    if args.get("delete"):
        await client.delete_gist(args["gist_id"])
        return text(f"gist {args['gist_id']} deleted")
    files = _files(args.get("files"), args.get("filename"), args.get("content"))
    gist = await client.update_gist(args["gist_id"], files, args.get("description"))
    return text(f"gist updated: {gist['html_url']}")
