import logging
import posixpath

from unsafie.agent.tools.base import ToolContext, error, guarded, schema, text
from unsafie.agent.tools.files import deliver
from unsafie.agent.tools.registry import register
from unsafie.agent.tools.ssh.context import SERVER
from unsafie.mime import (
    decode_text,
    human_size,
    image_problem,
    image_result,
    number_lines,
    sniff_mime,
)
from unsafie.ssh import binding, pool

logger = logging.getLogger(__name__)

READ_LIMIT = 400_000


@register(
    SERVER,
    "ssh_hosts",
    "Servers the user has added: alias, address, host key fingerprint, live connections.",
    schema([]),
)
@guarded
async def ssh_hosts(ctx: ToolContext, args: dict) -> dict:
    hosts = await binding.hosts(ctx.user_id)
    if not hosts:
        return text("no servers added. The user adds one with /ssh add alias user@host")
    live = {s["host_id"] for s in pool.pool.stats() if s["user_id"] == ctx.user_id and s["alive"]}
    lines = [binding.describe(h) + (" · connected" if h.id in live else "") for h in hosts]
    return text("\n".join(lines))


@register(
    SERVER,
    "ssh_run",
    "Run a shell command on a server over SSH. host — alias (the only server by default). "
    "timeout in seconds. Returns exit code, stdout and stderr. The command runs non-interactively: "
    "no prompts, no sudo password. Destructive commands only at an explicit request of the user.",
    schema(["command"], command=str, host=str, timeout=int),
)
@guarded
async def ssh_run(ctx: ToolContext, args: dict) -> dict:
    host = await binding.resolve(ctx.user_id, args.get("host"))
    result = await pool.run(ctx.user_id, host, args["command"], args.get("timeout"))
    head = f"{host.alias}$ {args['command']}\nexit={result.exit_code}"
    body = result.output or "(no output)"
    return text(f"{head}\n{body}")


@register(
    SERVER,
    "ssh_read",
    "Read a text file from a server with line numbers. start_line/end_line — a range.",
    schema(["path"], path=str, host=str, start_line=int, end_line=int),
)
@guarded
async def ssh_read(ctx: ToolContext, args: dict) -> dict:
    host = await binding.resolve(ctx.user_id, args.get("host"))
    data = await pool.read_file(ctx.user_id, host, args["path"])
    decoded = decode_text(data)
    if decoded is None:
        mime = sniff_mime(data, args["path"])
        return error(
            f"{args['path']} is binary ({mime}, {human_size(len(data))}). "
            "Use ssh_download to send it to the chat, or ssh_view for an image."
        )
    body, enc = decoded
    numbered, total = number_lines(body, args.get("start_line"), args.get("end_line"), READ_LIMIT)
    head = f"{host.alias}:{args['path']} [{total} lines{'' if enc == 'utf-8' else ', ' + enc}]\n"
    return text(head + (numbered or "<empty file>"))


@register(
    SERVER,
    "ssh_write",
    "Write a text file to a server (overwrites). Use ssh_run with sed/tee for a partial change, or "
    "read, change and write back.",
    schema(["path", "content"], path=str, content=str, host=str),
)
@guarded
async def ssh_write(ctx: ToolContext, args: dict) -> dict:
    host = await binding.resolve(ctx.user_id, args.get("host"))
    n = await pool.write_file(ctx.user_id, host, args["path"], args["content"].encode())
    return text(f"written {host.alias}:{args['path']} ({human_size(n)})")


@register(
    SERVER,
    "ssh_list",
    "List a directory on the server (a directory has a trailing slash).",
    schema(["path"], path=str, host=str),
)
@guarded
async def ssh_list(ctx: ToolContext, args: dict) -> dict:
    host = await binding.resolve(ctx.user_id, args.get("host"))
    names = await pool.list_dir(ctx.user_id, host, args["path"])
    if not names:
        return text(f"{host.alias}:{args['path']} is empty")
    return text(f"{host.alias}:{args['path']}\n" + "\n".join(names))


@register(
    SERVER,
    "ssh_view",
    "Look at an image stored on the server (jpeg/png/gif/webp).",
    schema(["path"], path=str, host=str),
)
@guarded
async def ssh_view(ctx: ToolContext, args: dict) -> dict:
    host = await binding.resolve(ctx.user_id, args.get("host"))
    data = await pool.read_file(ctx.user_id, host, args["path"])
    mime = sniff_mime(data, args["path"])
    if problem := image_problem(data, mime):
        return error(f"cannot view: {problem}")
    return image_result(
        data, mime, f"{host.alias}:{args['path']} ({mime}, {human_size(len(data))})"
    )


@register(
    SERVER,
    "ssh_download",
    "Take a file from the server and send it to the user in the chat.",
    schema(["path"], path=str, host=str, caption=str),
    replies=True,
)
@guarded
async def ssh_download(ctx: ToolContext, args: dict) -> dict:
    host = await binding.resolve(ctx.user_id, args.get("host"))
    data = await pool.read_file(ctx.user_id, host, args["path"])
    return await deliver(ctx, data, posixpath.basename(args["path"]), caption=args.get("caption"))


@register(
    SERVER,
    "ssh_upload",
    "Put a file received in Telegram (file_id) onto the server at path.",
    schema(["file_id", "path"], file_id=str, path=str, host=str),
)
@guarded
async def ssh_upload(ctx: ToolContext, args: dict) -> dict:
    from unsafie.telegram.retry import download

    host = await binding.resolve(ctx.user_id, args.get("host"))
    data = await download(ctx.bot, args["file_id"], f"{ctx.prefix} download")
    n = await pool.write_file(ctx.user_id, host, args["path"], data)
    return text(f"uploaded {host.alias}:{args['path']} ({human_size(n)})")


@register(
    SERVER,
    "ssh_disconnect",
    "Close the open connection to a server (it reopens on the next command). Useful after changing "
    "keys or when a session hangs.",
    schema([], host=str),
)
@guarded
async def ssh_disconnect(ctx: ToolContext, args: dict) -> dict:
    if args.get("host"):
        host = await binding.resolve(ctx.user_id, args["host"])
        closed = await pool.pool.disconnect(ctx.user_id, host.id)
        return text(f"{host.alias}: {'disconnected' if closed else 'was not connected'}")
    n = 0
    for host in await binding.hosts(ctx.user_id):
        if await pool.pool.disconnect(ctx.user_id, host.id):
            n += 1
    return text(f"{n} connection(s) closed")
