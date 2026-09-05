import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.gh.format import release_line
from unsafie.agent.tools.registry import register
from unsafie.github.errors import GithubError, NotFound

logger = logging.getLogger(__name__)

REPO_ARGS = dict(repo=str)


@register(
    SERVER,
    "release_list",
    "Releases of a repository. tag — show one release in full.",
    schema([], tag=str, limit=int, **REPO_ARGS),
)
@guarded
async def release_list(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    if tag := args.get("tag"):
        rel = await state.client.release(tag)
        if rel is None:
            raise NotFound(f"no release with tag {tag}")
        assets = "\n".join(
            f"  {a['name']} ({a['download_count']} downloads)" for a in rel.get("assets") or []
        )
        return text(
            f"{release_line(rel)}\n{rel.get('html_url')}\n\n{rel.get('body') or ''}\n{assets}"
        )
    items = await state.client.releases(max(1, min(int(args.get("limit") or 20), 50)))
    if not items:
        return text(f"no releases in {state.repo.full}")
    return text(f"{state.repo.full}:\n" + "\n".join(release_line(r) for r in items))


@register(
    SERVER,
    "release_create",
    "Create a release: tag, name, body (markdown release notes), target — branch or commit, "
    "draft, prerelease.",
    schema(
        ["tag"], tag=str, name=str, body=str, target=str, draft=bool, prerelease=bool, **REPO_ARGS
    ),
)
@guarded
async def release_create(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    rel = await state.client.create_release(
        args["tag"],
        args.get("name"),
        args.get("body"),
        args.get("target"),
        bool(args.get("draft")),
        bool(args.get("prerelease")),
    )
    return text(f"release {rel['tag_name']} created: {rel['html_url']}")


@register(
    SERVER,
    "release_update",
    "Change a release by tag: name, body, draft, prerelease; delete=true removes it.",
    schema(
        ["tag"], tag=str, name=str, body=str, draft=bool, prerelease=bool, delete=bool, **REPO_ARGS
    ),
)
@guarded
async def release_update(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    rel = await state.client.release(args["tag"])
    if rel is None:
        raise NotFound(f"no release with tag {args['tag']}")
    if args.get("delete"):
        await state.client.delete_release(int(rel["id"]))
        return text(f"release {args['tag']} deleted")
    fields = {
        k: args[k] for k in ("name", "body", "draft", "prerelease") if args.get(k) is not None
    }
    if not fields:
        raise GithubError("nothing to change")
    updated = await state.client.update_release(int(rel["id"]), **fields)
    return text(f"release {updated['tag_name']} updated: " + ", ".join(fields))
