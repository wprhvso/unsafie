import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.fluent import t
from unsafie.ssh import binding, keys
from unsafie.ssh.errors import SshError
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


def build_ssh_router() -> Router:
    router = Router()

    @router.message(Command("ssh"))
    async def ssh_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        parts = (command.args or "").split()
        action = parts[0].lower() if parts else ""
        try:
            if action in ("", "list"):
                hosts = await binding.hosts(user_id)
                if not hosts:
                    await answer(message, bot_id, t("ssh-empty", locale))
                    return
                lines = [t("ssh-list", locale)] + [f"· {binding.describe(h)}" for h in hosts]
                await answer(message, bot_id, "\n".join(lines))
                return
            if action == "key":
                rotate = len(parts) > 1 and parts[1].lower() in ("new", "rotate")
                _, public = await (keys.rotate(user_id) if rotate else keys.ensure(user_id))
                key = t("ssh-key-rotated", locale) if rotate else t("ssh-key", locale)
                await answer(message, bot_id, f"{key}\n\n`{public}`")
                return
            if action == "add":
                if len(parts) < 3:
                    await answer(message, bot_id, t("ssh-usage", locale))
                    return
                await keys.ensure(user_id)
                host = await binding.add(
                    user_id, parts[1], parts[2], parts[3] if len(parts) > 3 else None
                )
                await answer(
                    message, bot_id, t("ssh-added", locale, alias=host.alias, target=host.label)
                )
                return
            if action in ("rm", "remove", "del"):
                if len(parts) < 2:
                    await answer(message, bot_id, t("ssh-usage", locale))
                    return
                removed = await binding.remove(user_id, parts[1])
                await answer(message, bot_id, t("ssh-removed", locale, alias=removed.alias))
                return
        except SshError as e:
            await answer(message, bot_id, str(e))
            return
        await answer(message, bot_id, t("ssh-usage", locale))

    return router
