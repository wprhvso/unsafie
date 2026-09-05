import logging
import re
from collections.abc import Callable
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from unsafie.agent.hooks import build_hooks
from unsafie.agent.prompt import SYSTEM_PROMPT
from unsafie.agent.tools import ToolContext, build_servers
from unsafie.agent.trace import Recorder
from unsafie.settings import settings

logger = logging.getLogger(__name__)

BUFFER_SIZE = 16 * 1024 * 1024
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "low"


def chat_cwd(bot_id: int, chat_id: int) -> Path:
    return settings.chats_dir / str(bot_id) / str(chat_id)


def transcript_path(bot_id: int, chat_id: int, session_id: str) -> Path:
    project = re.sub(r"[^A-Za-z0-9]", "-", str(chat_cwd(bot_id, chat_id).resolve()))
    return settings.claude_config_dir / "projects" / project / f"{session_id}.jsonl"


def build_options(
    ctx: ToolContext,
    *,
    resume: str | None,
    fork: bool,
    session_id: str | None,
    model: str,
    effort: str,
    budget_usd: float,
    context: str,
    servers: list[str],
    env: dict[str, str],
    stderr: Callable[[str], None],
    recorder: Recorder | None = None,
) -> ClaudeAgentOptions:
    cwd = chat_cwd(ctx.bot_id, ctx.chat_id)
    cwd.mkdir(parents=True, exist_ok=True)
    mcp, allowed = build_servers(ctx, servers)
    system_prompt = SYSTEM_PROMPT + (f"\n{context}\n" if context else "")
    logger.debug(
        "%s options resume=%s fork=%s session=%s model=%s effort=%s budget=%.6f servers=%s",
        ctx.prefix,
        resume,
        fork,
        session_id,
        model,
        effort,
        budget_usd,
        servers,
    )
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        tools=["WebSearch", "WebFetch"],
        mcp_servers=mcp,
        allowed_tools=allowed,
        permission_mode="acceptEdits",
        strict_mcp_config=True,
        setting_sources=[],
        hooks=build_hooks(ctx.prefix, ctx.turn_id, recorder),
        cwd=cwd,
        resume=resume,
        fork_session=fork,
        session_id=session_id if resume is None else None,
        max_budget_usd=budget_usd,
        max_buffer_size=BUFFER_SIZE,
        effort=effort,
        env=env,
        stderr=stderr,
    )
