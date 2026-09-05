import logging
from datetime import UTC, datetime, timedelta

from unsafie.agent.tools.base import ToolContext, error, schema, text
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.repositories.history import HistoryRepository, Hit
from unsafie.scheduler.when import WhenError, duration

logger = logging.getLogger(__name__)

SERVER = "tg"
SNIPPET = 600


def _when(raw: str | None, now: datetime) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int((now - timedelta(seconds=duration(raw))).timestamp())
    except WhenError:
        pass
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise WhenError(
            f"cannot parse date '{raw}': use ISO (2026-09-01) or an age (7d, 12h)"
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def _row(h: Hit, full: bool = False) -> str:
    who = "bot" if h.who == "bot" else f"@{h.name}" if h.name else f"user {h.user_id}"
    body = h.body.replace("\n", " ⏎ ") if not full else h.body
    if not full and len(body) > SNIPPET:
        body = body[:SNIPPET] + "…"
    reply = f" ↩{h.reply_to}" if h.reply_to else ""
    return f"[{h.message_id}] {h.when}Z {who}{reply}: {body}"


@register(
    SERVER,
    "history_search",
    "Search this chat's history (all conversations, not only the current branch): user messages and "
    "bot replies. query — words (AND, prefix match, any language); who: any | user | bot; "
    "since / until — ISO date or an age ('7d', '12h'); limit up to 50. Returns message_id, time, "
    "author and a highlighted snippet; details via history_get(message_id).",
    schema(["query"], query=str, who=str, since=str, until=str, limit=int),
)
async def history_search(ctx: ToolContext, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return error("query is empty")
    who = (args.get("who") or "any").strip().lower()
    if who not in ("any", "user", "bot"):
        return error("who must be any | user | bot")
    now = datetime.now(UTC)
    try:
        since, until = _when(args.get("since"), now), _when(args.get("until"), now)
    except WhenError as e:
        return error(str(e))
    limit = max(1, min(int(args.get("limit") or 20), 50))
    async with SessionLocal() as session:
        hits, how = await HistoryRepository(session).search(
            ctx.bot_id, ctx.chat_id, query, who=who, since=since, until=until, limit=limit
        )
    if not hits:
        return text("nothing found; try other or shorter words")
    head = f"{len(hits)} hits ({'full-text' if how == 'fts' else 'substring'}), <b>…</b> marks matches:"
    return text(head + "\n" + "\n".join(_row(h) for h in hits))


@register(
    SERVER,
    "history_get",
    "A slice of chat history: message_id plus `around` messages before and after (default 5), full "
    "text, with reply markers (↩id). Without message_id — the last `limit` messages of the chat "
    "(before — page backwards).",
    schema([], message_id=int, around=int, limit=int, before=int),
)
async def history_get(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        repo = HistoryRepository(session)
        if args.get("message_id"):
            radius = max(0, min(int(args.get("around") or 5), 30))
            hits = await repo.around(ctx.bot_id, ctx.chat_id, int(args["message_id"]), radius)
        else:
            limit = max(1, min(int(args.get("limit") or 20), 100))
            hits = await repo.recent(ctx.bot_id, ctx.chat_id, limit, args.get("before"))
    if not hits:
        return text("no messages in this range")
    body = "\n\n".join(_row(h, full=True) for h in hits)
    if len(body) > 60_000:
        body = body[:60_000] + "\n…(truncated, narrow around/limit)"
    return text(body)
