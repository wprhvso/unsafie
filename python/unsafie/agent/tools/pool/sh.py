import logging

from unsafie.agent import live
from unsafie.agent.tools.base import ToolContext, error, guarded, schema, text
from unsafie.agent.tools.pool.context import SERVER
from unsafie.agent.tools.registry import register
from unsafie.mime import human_size, image_block, image_problem, sniff_mime
from unsafie.pool import blobs, channel, leases
from unsafie.settings import settings
from unsafie_wire import markers

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Run a shell command on your machine in the pool: a fresh Ubuntu box, root, with the "
    "`unsafie` CLI preinstalled and already authorized as this user and this chat.\n"
    "The CLI is how you reach everything that is not a file or a process: `unsafie say` writes "
    "to this chat, `unsafie file` sends a file, `unsafie page create` publishes a page and "
    "prints its link, `unsafie chrome …` drives a real Chrome, `unsafie repo clone` gives you a "
    "real git checkout, `unsafie machines/take/release` manages machines, `unsafie blob|kv|secret` "
    "keeps state between turns.\n"
    "`unsafie help` lists the groups, `unsafie <group> --help` explains one, `unsafie help --json` "
    "returns the whole index in a single call — read it instead of guessing.\n"
    "Plain shell works too: git, gh, rg, fd, jq, curl, uv, node, go, cargo, docker are there.\n"
    "Screenshots and files the CLI produces come back inline: you see the picture itself.\n"
    "Without a machine the first command takes one for you. The machine is single use — "
    "releasing destroys it, so push to git or `unsafie blob put` whatever must survive. "
    "Destructive commands only at an explicit request of the user."
)

HEAD_LIMIT = 400


@register(
    SERVER,
    "sh",
    DESCRIPTION,
    schema(
        ["command"],
        command=str,
        machine=str,
        timeout=int,
        stdin=str,
        background=bool,
    ),
)
@guarded
async def sh(ctx: ToolContext, args: dict) -> dict:
    command = str(args.get("command") or "").strip()
    if not command:
        return error("nothing to run")
    if not settings.pool_enabled:
        return error("the pool is switched off on this server")
    if args.get("machine"):
        machine = await leases.resolve(ctx.user_id, str(args["machine"]))
    else:
        machine = await leases.ensure(ctx.user_id, ctx.chat_id, ctx.turn_id, ctx.bot_id)
    name = machine.alias or machine.name
    if args.get("background"):
        job = await channel.send(
            machine.name,
            command,
            user_id=ctx.user_id,
            turn_id=ctx.turn_id,
            timeout=args.get("timeout"),
            background=True,
        )
        return text(
            f"{name}$ {command}\nstarted in the background as {job}\n"
            f"follow it with: unsafie job logs {job} -f"
        )
    result = await channel.run(
        machine.name,
        command,
        user_id=ctx.user_id,
        turn_id=ctx.turn_id,
        timeout=args.get("timeout"),
        stdin=args.get("stdin"),
    )
    body, blocks = markers.split(result.output)
    head = f"{name}$ {command[:HEAD_LIMIT]}"
    if result.timed_out:
        head += f"\nno exit code after {result.seconds:.0f}s — the command may still be running"
    else:
        head += f"\nexit={result.exit_code} in {result.seconds:.1f}s"
    if result.truncated:
        head += f" (output cut at {human_size(settings.pool_max_output)})"
    content: list[dict] = [{"type": "text", "text": f"{head}\n{body.strip() or '(no output)'}"}]
    content += await _blocks(ctx, blocks)
    answer: dict = {"content": content}
    if result.timed_out:
        answer["is_error"] = True
    if any(block.kind == markers.BlockKind.SENT for block in blocks):
        answer["replied"] = True
    return answer


async def _blocks(ctx: ToolContext, blocks: list[markers.Block]) -> list[dict]:
    out: list[dict] = []
    for block in blocks:
        if block.kind == markers.BlockKind.IMAGE:
            rendered = await _image(ctx, block)
            if rendered is not None:
                out.append(rendered)
            continue
        if block.kind in (markers.BlockKind.NOTE, markers.BlockKind.PROGRESS):
            live.emit(ctx.turn_id, "note", text=str(block.data.get("text") or ""))
            continue
        if block.kind == markers.BlockKind.LINK:
            out.append(
                {
                    "type": "text",
                    "text": f"{block.data.get('title') or 'link'}: {block.data.get('url')}",
                }
            )
            continue
        if block.kind == markers.BlockKind.RESULT:
            out.append({"type": "text", "text": f"result: {block.data.get('value')}"})
            continue
        if block.kind == markers.BlockKind.ERROR:
            out.append({"type": "text", "text": f"error: {block.data.get('message')}"})
    return out


async def _image(ctx: ToolContext, block: markers.Block) -> dict | None:
    key = str(block.data.get("blob") or "")
    if not key:
        return None
    data = await blobs.get(ctx.user_id, key)
    if data is None:
        return {"type": "text", "text": f"the screenshot at {key} is gone"}
    mime = str(block.data.get("mime") or sniff_mime(data, key))
    if problem := image_problem(data, mime):
        return {"type": "text", "text": f"cannot show {key}: {problem}"}
    live.emit(ctx.turn_id, "note", text=f"image {key} ({human_size(len(data))})")
    return image_block(data, mime)
