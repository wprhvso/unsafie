import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)

TEXT_EXPR = "coalesce(u.payload #>> '{message,text}', u.payload #>> '{message,caption}', '')"
IN_TSV = f"to_tsvector('simple', {TEXT_EXPR})"
OUT_TSV = "to_tsvector('simple', r.content)"

INBOUND_BASE = f"""
    SELECT 'user' AS who, u.message_id, u.user_id,
           coalesce(u.payload #>> '{{message,from,username}}', u.payload #>> '{{message,from,first_name}}') AS name,
           coalesce((u.payload #>> '{{message,date}}')::bigint, extract(epoch FROM u.created_at)::bigint) AS ts,
           {TEXT_EXPR} AS body,
           (u.payload #>> '{{message,reply_to_message,message_id}}')::bigint AS reply_to
    FROM updates u
    WHERE u.bot_id = :bot_id AND u.chat_id = :chat_id AND u.message_id IS NOT NULL
"""
OUTBOUND_BASE = """
    SELECT 'bot' AS who, (r.message_ids ->> 0)::bigint AS message_id, NULL::bigint AS user_id, NULL::text AS name,
           extract(epoch FROM r.created_at)::bigint AS ts, r.content AS body, r.reply_to
    FROM responses r
    WHERE r.bot_id = :bot_id AND r.chat_id = :chat_id AND jsonb_array_length(r.message_ids) > 0
"""

SEARCH_SQL = text(f"""
WITH q AS (SELECT to_tsquery('simple', :tsq) AS ts),
inbound AS (
    SELECT 'user' AS who, u.message_id, u.user_id,
           coalesce(u.payload #>> '{{message,from,username}}', u.payload #>> '{{message,from,first_name}}') AS name,
           coalesce((u.payload #>> '{{message,date}}')::bigint, extract(epoch FROM u.created_at)::bigint) AS ts,
           {TEXT_EXPR} AS body,
           ts_rank({IN_TSV}, q.ts) AS rank
    FROM updates u, q
    WHERE u.bot_id = :bot_id AND u.chat_id = :chat_id AND u.message_id IS NOT NULL
      AND (CAST(:who AS text) IN ('any', 'user'))
      AND {IN_TSV} @@ q.ts
),
outbound AS (
    SELECT 'bot' AS who, (r.message_ids ->> 0)::bigint AS message_id, NULL::bigint AS user_id, NULL::text AS name,
           extract(epoch FROM r.created_at)::bigint AS ts,
           r.content AS body,
           ts_rank({OUT_TSV}, q.ts) AS rank
    FROM responses r, q
    WHERE r.bot_id = :bot_id AND r.chat_id = :chat_id AND jsonb_array_length(r.message_ids) > 0
      AND (CAST(:who AS text) IN ('any', 'bot'))
      AND {OUT_TSV} @@ q.ts
),
hits AS (SELECT * FROM inbound UNION ALL SELECT * FROM outbound)
SELECT who, message_id, user_id, name, ts, rank,
       ts_headline('simple', body, (SELECT ts FROM q),
                   'MaxWords=40, MinWords=15, MaxFragments=2, FragmentDelimiter= … ') AS snippet
FROM hits
WHERE (CAST(:since AS bigint) IS NULL OR ts >= CAST(:since AS bigint)) AND (CAST(:until AS bigint) IS NULL OR ts <= CAST(:until AS bigint))
ORDER BY rank DESC, ts DESC
LIMIT :limit
""")

LIKE_SQL = text(f"""
WITH inbound AS ({INBOUND_BASE} AND (CAST(:who AS text) IN ('any', 'user')) AND {TEXT_EXPR} ILIKE :pattern),
outbound AS ({OUTBOUND_BASE} AND (CAST(:who AS text) IN ('any', 'bot')) AND r.content ILIKE :pattern),
hits AS (SELECT * FROM inbound UNION ALL SELECT * FROM outbound)
SELECT who, message_id, user_id, name, ts, 0::real AS rank, body AS snippet
FROM hits
WHERE (CAST(:since AS bigint) IS NULL OR ts >= CAST(:since AS bigint)) AND (CAST(:until AS bigint) IS NULL OR ts <= CAST(:until AS bigint))
ORDER BY ts DESC
LIMIT :limit
""")

AROUND_SQL = text(f"""
WITH inbound AS ({INBOUND_BASE}), outbound AS ({OUTBOUND_BASE}),
allm AS (SELECT * FROM inbound UNION ALL SELECT * FROM outbound)
SELECT who, message_id, user_id, name, ts, body, reply_to
FROM allm
WHERE message_id BETWEEN :lo AND :hi
ORDER BY message_id
LIMIT :limit
""")

RECENT_SQL = text(f"""
WITH inbound AS ({INBOUND_BASE}), outbound AS ({OUTBOUND_BASE}),
allm AS (SELECT * FROM inbound UNION ALL SELECT * FROM outbound)
SELECT who, message_id, user_id, name, ts, body, reply_to
FROM allm
WHERE (CAST(:before AS bigint) IS NULL OR message_id < CAST(:before AS bigint))
ORDER BY message_id DESC
LIMIT :limit
""")


@dataclass(frozen=True)
class Hit:
    who: str
    message_id: int | None
    user_id: int | None
    name: str | None
    ts: int
    body: str
    rank: float = 0.0
    reply_to: int | None = None

    @property
    def when(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=UTC).strftime("%Y-%m-%d %H:%M")


def tsquery(query: str) -> str:
    words = [w.replace("-", "") for w in WORD_RE.findall(query.lower()) if len(w) > 1]
    return " & ".join(f"{w}:*" for w in words if w)


class HistoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(
        self,
        bot_id: int,
        chat_id: int,
        query: str,
        *,
        who: str = "any",
        since: int | None = None,
        until: int | None = None,
        limit: int = 20,
    ) -> tuple[list[Hit], str]:
        params = {
            "bot_id": bot_id,
            "chat_id": chat_id,
            "who": who,
            "since": since,
            "until": until,
            "limit": limit,
        }
        tsq = tsquery(query)
        if tsq:
            rows = (await self.session.execute(SEARCH_SQL, {**params, "tsq": tsq})).all()
            if rows:
                return [
                    Hit(r.who, r.message_id, r.user_id, r.name, int(r.ts), r.snippet, float(r.rank))
                    for r in rows
                ], "fts"
        pattern = "%" + query.strip().replace("%", r"\%").replace("_", r"\_") + "%"
        rows = (await self.session.execute(LIKE_SQL, {**params, "pattern": pattern})).all()
        return [
            Hit(r.who, r.message_id, r.user_id, r.name, int(r.ts), r.snippet) for r in rows
        ], "like"

    async def around(self, bot_id: int, chat_id: int, message_id: int, radius: int) -> list[Hit]:
        rows = (
            await self.session.execute(
                AROUND_SQL,
                {
                    "bot_id": bot_id,
                    "chat_id": chat_id,
                    "lo": message_id - radius * 3,
                    "hi": message_id + radius * 3,
                    "limit": radius * 2 + 1 + 40,
                },
            )
        ).all()
        hits = [
            Hit(
                r.who, r.message_id, r.user_id, r.name, int(r.ts), r.body or "", reply_to=r.reply_to
            )
            for r in rows
        ]
        idx = next((i for i, h in enumerate(hits) if h.message_id == message_id), None)
        if idx is None:
            return [h for h in hits if abs((h.message_id or 0) - message_id) <= radius]
        return hits[max(0, idx - radius) : idx + radius + 1]

    async def recent(
        self, bot_id: int, chat_id: int, limit: int, before: int | None = None
    ) -> list[Hit]:
        rows = (
            await self.session.execute(
                RECENT_SQL, {"bot_id": bot_id, "chat_id": chat_id, "limit": limit, "before": before}
            )
        ).all()
        hits = [
            Hit(
                r.who, r.message_id, r.user_id, r.name, int(r.ts), r.body or "", reply_to=r.reply_to
            )
            for r in rows
        ]
        hits.reverse()
        return hits
