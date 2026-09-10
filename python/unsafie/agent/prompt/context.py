from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.agent.session import Ctx
from unsafie.database.repositories.chat import ChatRepository
from unsafie.database.repositories.user import UserRepository
from unsafie.github import pat
from unsafie.scheduler.when import zone
from unsafie.settings import settings
from unsafie.ssh import binding

REMINDER = (
    "Reminder: Write ONLY a single executable Bash code block. "
    "Do not write prose outside code blocks. Nothing written outside code blocks reaches the user. "
    "All messages must be sent via 'unsafie chat send ...' inside your code. "
    "When finished, run 'unsafie stop' to conclude your turn."
)

INLINE_REMINDER = (
    "CRITICAL CONTEXT: YOU ARE EXECUTING IN TELEGRAM INLINE MODE.\n"
    "The user invoked you via @bot in an external chat. Target: inline_message_id={inline_message_id}.\n\n"
    "# ABSOLUTE OPERATIONAL LIMITATIONS OF INLINE MODE:\n"
    "1. NO CHAT ACCESS: You do NOT have a target chat_id. NEVER call `unsafie chat send`, `unsafie chat send-file`. They will fail.\n"
    '2. DELIVERING RESULTS: To output text to the user, you MUST use `unsafie inline edit "<markdown>"`.\n'
    "3. ONE-SHOT STATELESS TURN: This is a single, isolated query. There is NO chat history, NO previous turns, "
    "and NO future replies. Answer completely in this single turn.\n"
    "4. STRICT LENGTH LIMIT (4096 CHARS): The inline message text cannot exceed 4096 characters. "
    "For code, long tables, or detailed analysis, publish a page via `unsafie pages create <file>` and put the link "
    'into your concise inline response: `unsafie inline edit "Summary...\\n\\nFull details: $URL"`.\n'
    "5. SPEED IS ESSENTIAL: The user is actively looking at the chat where 'Generating answer...' is displayed. "
    "Deliver your answer quickly and directly."
)


async def time_context(session: AsyncSession, ctx: Ctx) -> str:
    user = await UserRepository(session).get(ctx.user_id)
    name = user.timezone if user and user.timezone else None
    try:
        tz = zone(name or settings.default_timezone)
    except ValueError:
        tz = zone("UTC")
    now = datetime.now(UTC).astimezone(tz)
    line = f"Now: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')}), timezone {tz.key}"
    if not name:
        line += " (user timezone not set, default UTC used)"
    line += f". User locale: {ctx.locale}."
    return line


async def accounts_context(ctx: Ctx) -> str:
    rows = await pat.accounts_of(ctx.user_id)
    if not rows:
        return "GitHub: no account attached."
    logins = ", ".join(row.login for row in rows)
    tail = " (unsafie github use <login> switches account)" if len(rows) > 1 else ""
    return f"GitHub accounts: {logins}{tail}."


async def servers_context(ctx: Ctx) -> str:
    hosts = await binding.hosts(ctx.user_id)
    if not hosts:
        return ""
    listed = "; ".join(f"{host.alias} ({host.label})" for host in hosts)
    return f"SSH servers configured in ~/.ssh: {listed}."


async def chat_system_context(session: AsyncSession, ctx: Ctx) -> str:
    chat = await ChatRepository(session).get(ctx.bot_id, ctx.chat_id)
    if chat and chat.system:
        return f"User system instructions for this chat:\n{chat.system}"
    return ""


async def build_context(session: AsyncSession, ctx: Ctx) -> str:
    reminder = (
        INLINE_REMINDER.format(inline_message_id=ctx.inline_message_id)
        if ctx.inline_message_id
        else REMINDER
    )
    parts = [
        await time_context(session, ctx),
        await accounts_context(ctx),
        await servers_context(ctx),
        await chat_system_context(session, ctx),
        reminder,
    ]
    return "\n".join(part for part in parts if part)
