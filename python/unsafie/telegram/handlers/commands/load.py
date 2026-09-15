import tarfile
import tempfile
from pathlib import Path
from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie import events
from unsafie.agent import segments
from unsafie.agent.prompt import SYSTEM_PROMPT
from unsafie.database import SessionLocal
from unsafie.database.models.response import ResponseKind
from unsafie.database.models.turn import TurnStatus
from unsafie.database.repositories.github import RepoRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.update import UpdateRepository
from unsafie.fluent import t
from unsafie.github import pat
from unsafie.github.client.repo import RepoClient
from unsafie.github.errors import GithubError
from unsafie.github.vfs import SKIP_DIRS
from unsafie.log import get_logger
from unsafie.mime import decode_text, human_size
from unsafie.settings import settings
from unsafie.telegram import sender
from unsafie.telegram.chat_action import typing
from unsafie.telegram.handlers.locale import locale_for

logger = get_logger(__name__)


def parse_repo_arg(arg: str) -> tuple[str, str, str | None]:
    val = arg.strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if val.startswith(prefix):
            val = val[len(prefix) :]
            break
    val = val.removesuffix(".git").strip("/")
    branch: str | None = None
    if "/tree/" in val:
        repo_part, _, branch_part = val.partition("/tree/")
        val = repo_part.strip("/")
        branch = branch_part.strip("/") or None
    elif "@" in val:
        repo_part, _, branch_part = val.partition("@")
        val = repo_part.strip("/")
        branch = branch_part.strip("/") or None
    parts = val.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        msg = f"Invalid repository '{arg}', expected owner/repo"
        raise ValueError(msg)
    return parts[0], parts[1], branch


def make_fence(content: str) -> str:
    count = 3
    while "`" * count in content:
        count += 1
    return "`" * count


def format_repo_markdown(
    owner: str,
    name: str,
    branch: str | None,
    files: dict[str, str],
) -> str:
    ref_suffix = f"@{branch}" if branch else ""
    lines = [f"# Repository: {owner}/{name}{ref_suffix}\n"]
    for path in sorted(files.keys()):
        content = files[path]
        if content.startswith("[Binary file, "):
            lines.append(f"## {path}\n\n{content}\n")
        else:
            ext = Path(path).suffix.lstrip(".")
            fence = make_fence(content)
            lines.append(f"## {path}\n\n{fence}{ext}\n{content}\n{fence}\n")
    return "\n".join(lines)


async def fetch_repo_files(
    user_id: int,
    owner: str,
    name: str,
    branch: str | None,
) -> dict[str, str]:
    token: str | None = None
    accounts = await pat.accounts_of(user_id)
    for acc in accounts:
        if acc.token and acc.login.lower() == owner.lower():
            token = acc.token
            break
    if token is None and accounts and accounts[0].token:
        token = accounts[0].token

    app_fallback = None
    async with SessionLocal() as session:
        repo_row = await RepoRepository(session).by_full_name(owner, name)
        if repo_row:
            app_fallback = pat.app_provider(repo_row)

    client = RepoClient(owner, name, token=token or "", fallback=app_fallback)
    url = f"{client.base}/tarball/{branch}" if branch else f"{client.base}/tarball"

    with tempfile.TemporaryDirectory(prefix="unsafie-load-") as temp_dir:
        archive_path = Path(temp_dir) / "repo.tar.gz"
        size = await client.stream(url, archive_path, limit=settings.github_bulk_max_bytes)
        if size is None:
            msg = f"Repository {owner}/{name} archive exceeds size limit"
            raise GithubError(msg)

        files: dict[str, str] = {}
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                if member.size > settings.github_bulk_file_bytes:
                    continue
                _, _, rel_path = member.name.partition("/")
                if not rel_path or any(
                    rel_path.startswith(d) or f"/{d}" in rel_path for d in SKIP_DIRS
                ):
                    continue
                if Path(rel_path).name in (".DS_Store", "Thumbs.db"):
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                raw_bytes = handle.read()
                decoded = decode_text(raw_bytes)
                if decoded is not None:
                    files[rel_path] = decoded[0]
                else:
                    files[rel_path] = f"[Binary file, {human_size(len(raw_bytes))}]"
        return files


def build_load_router() -> Router:
    router = Router()

    @router.message(Command("load"))
    async def load_handler(
        message: Message,
        command: CommandObject,
        bot_id: int,
        update_db_id: int | None = None,
    ) -> None:
        if message.from_user is None or message.bot is None:
            return
        user_id = message.from_user.id
        chat_id = message.chat.id
        locale = await locale_for(user_id, message.from_user)

        args = (command.args or "").split()
        if not args:
            await sender.answer(message, bot_id, t("commands-load-usage", locale))
            return

        parsed_targets: list[tuple[str, str, str | None]] = []
        for arg in args:
            try:
                owner, name, branch = parse_repo_arg(arg)
                parsed_targets.append((owner, name, branch))
            except ValueError as e:
                await sender.answer(message, bot_id, str(e))
                return

        loaded_repos: dict[tuple[str, str, str | None], dict[str, str]] = {}
        failed: list[tuple[str, str]] = []

        async with typing(message.bot, chat_id):
            for owner, name, branch in parsed_targets:
                label = f"{owner}/{name}" + (f"@{branch}" if branch else "")
                try:
                    files = await fetch_repo_files(user_id, owner, name, branch)
                    loaded_repos[(owner, name, branch)] = files
                except GithubError as e:
                    failed.append((label, str(e)))
                except Exception as e:
                    logger.exception("Failed to load repo %s", label)
                    failed.append((label, str(e)))

        if not loaded_repos:
            error_msgs = "\n".join(f"· {repo}: {err}" for repo, err in failed)
            await sender.answer(
                message,
                bot_id,
                t("commands-load-all-failed", locale, errors=error_msgs),
            )
            return

        repo_markdowns: list[str] = []
        for (owner, name, branch), files in loaded_repos.items():
            repo_markdowns.append(format_repo_markdown(owner, name, branch, files))

        total_markdown = "\n\n---\n\n".join(repo_markdowns)
        total_chars = len(total_markdown)
        total_files = sum(len(files) for files in loaded_repos.values())
        successful_names = [f"{o}/{n}" + (f"@{b}" if b else "") for (o, n, b) in loaded_repos]
        repos_str = ", ".join(f"`{name}`" for name in successful_names)

        reply_to_msg_id = message.reply_to_message.message_id if message.reply_to_message else None
        async with SessionLocal() as session:
            turns_repo = TurnRepository(session)
            parent = None
            if reply_to_msg_id:
                parent = await turns_repo.owner(bot_id, chat_id, reply_to_msg_id)
            turn = await turns_repo.create(
                bot_id=bot_id,
                chat_id=chat_id,
                user_id=user_id,
                parent=parent,
                reply_to=message.message_id,
            )
            if update_db_id is not None:
                await UpdateRepository(session).attach(update_db_id, turn.id)

        events.publish(
            "turn.started",
            turn_id=str(turn.id),
            root_id=str(turn.root_id),
            bot_id=turn.bot_id,
            chat_id=turn.chat_id,
            user_id=turn.user_id,
            resumed=0,
        )

        history = await segments.load(turn) if parent else None
        system_prompt = (history.system if history else None) or SYSTEM_PROMPT
        segment: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": f"Repository files loaded into context ({', '.join(successful_names)}):\n\n{total_markdown}",
            },
            {
                "role": "assistant",
                "content": f"Successfully loaded {total_chars} characters from {', '.join(successful_names)} ({total_files} files).",
            },
        ]
        await segments.save(turn, segment, system=system_prompt)

        note = f"Loaded {total_chars} chars from {', '.join(successful_names)}"
        async with SessionLocal() as session:
            await TurnRepository(session).finish(turn.id, TurnStatus.DONE, note)

        events.publish(
            "turn.finished",
            turn_id=str(turn.id),
            root_id=str(turn.root_id),
            bot_id=turn.bot_id,
            chat_id=turn.chat_id,
            user_id=turn.user_id,
            status=str(TurnStatus.DONE),
            note=note,
        )

        chars_display = (
            f"{total_chars:,}".replace(",", " ") if locale == "ru" else f"{total_chars:,}"
        )
        text = t(
            "commands-load-success",
            locale,
            chars=chars_display,
            repos=repos_str,
            files=total_files,
        )
        if failed:
            failed_str = ", ".join(f"`{r}`" for r, _ in failed)
            text += "\n" + t("commands-load-partial-failed", locale, failed=failed_str)

        await sender.send(
            message.bot,
            bot_id=bot_id,
            chat_id=chat_id,
            markdown=text,
            kind=ResponseKind.SYSTEM,
            turn=turn,
            reply_to=message.message_id,
        )

    return router
