import logging

from unsafie.agent.tools.base import ToolContext, error, guarded, schema, text
from unsafie.agent.tools.files import deliver
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.registry import register
from unsafie.github import pat
from unsafie.mime import decode_text, human_size, image_problem, image_result, sniff_mime

logger = logging.getLogger(__name__)

MAX = 20 * 1024 * 1024


async def _get(ctx: ToolContext, state, url: str) -> bytes:
    import aiohttp

    token = await pat.token_for(ctx.user_id, state.repo)
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "unsafie"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.get(url, headers=headers) as r:
            if r.status >= 400:
                raise ValueError(f"HTTP {r.status} for {url}")
            data = await r.content.read(MAX + 1)
    if len(data) > MAX:
        raise ValueError(f"file exceeds {human_size(MAX)}")
    return data


@register(
    SERVER,
    "gh_fetch",
    "Download an attachment from a GitHub issue, PR or comment by its URL "
    "(github.com/user-attachments/…, private-user-images…). Uses the user's token, so private "
    "attachments work. mode = auto (default: view images, show text) | file (send to the chat).",
    schema(["url"], url=str, mode=str, repo=str),
)
@guarded
async def gh_fetch(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    url = args["url"].strip()
    try:
        data = await _get(ctx, state, url)
    except ValueError as e:
        return error(str(e))
    name = url.rstrip("/").rsplit("/", 1)[-1] or "attachment"
    mime = sniff_mime(data, name)
    mode = (args.get("mode") or "auto").lower()
    if mode == "file":
        return await deliver(ctx, data, name)
    if mime.startswith("image/"):
        if problem := image_problem(data, mime):
            return error(f"cannot view: {problem}")
        return image_result(data, mime, f"{name} ({mime}, {human_size(len(data))})")
    decoded = decode_text(data)
    if decoded is None:
        return await deliver(ctx, data, name, caption=f"{mime}, {human_size(len(data))}")
    body = decoded[0]
    return text(f"{name} ({mime}, {human_size(len(data))}):\n{body[:60_000]}")
