import asyncio
import logging
import time
from dataclasses import dataclass, field

from unsafie.agent import live
from unsafie.agent.session import Ctx
from unsafie.errors import OpsError
from unsafie.log import short
from unsafie.mime import human_size, image_block, image_problem, sniff_mime
from unsafie.pool import blobs, channel, leases
from unsafie.settings import settings
from unsafie_wire import markers

logger = logging.getLogger(__name__)

TOOL = "python"


@dataclass
class Block:
    call_id: str
    index: int
    code: str
    started_at: float = field(default_factory=time.monotonic)
    machine: str = ""
    exit_code: int | None = None
    output: str = ""
    seconds: float = 0.0
    truncated: bool = False
    error: str | None = None
    images: list[dict] = field(default_factory=list)
    sent: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def heading(self) -> str:
        where = self.machine or "no machine"
        if self.error:
            return f"[{self.index}] {where}: {self.error}"
        if self.exit_code is None:
            return f"[{self.index}] {where}: still running after {self.seconds:.0f}s"
        state = "ok" if self.ok else "raised"
        return f"[{self.index}] {where} · {state} in {self.seconds:.1f}s"


class Runner:
    """Runs every python call of one reply, in order, on the machine of this chat."""

    def __init__(self, ctx: Ctx, recorder) -> None:
        self.ctx = ctx
        self.recorder = recorder
        self.blocks: list[Block] = []
        self.seen: set[str] = set()
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    @property
    def count(self) -> int:
        return len(self.blocks)

    def handled(self, call_id: str) -> bool:
        return call_id in self.seen

    def start(self, call_id: str, code: str) -> Block:
        block = Block(call_id=call_id, index=len(self.blocks) + 1, code=code)
        self.blocks.append(block)
        self.seen.add(call_id)
        self.recorder.tool_started(call_id, TOOL, {"code": code})
        task = asyncio.create_task(
            self._run(block), name=f"python:{self.ctx.turn_id}:{block.index}"
        )
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return block

    def refuse(self, call_id: str, reason: str) -> Block:
        block = Block(call_id=call_id, index=len(self.blocks) + 1, code="")
        block.error = reason
        self.blocks.append(block)
        self.seen.add(call_id)
        self.recorder.tool_started(call_id, TOOL, {})
        self._finished(block)
        return block

    async def _run(self, block: Block) -> None:
        async with self.lock:
            try:
                machine = await leases.ensure(
                    self.ctx.user_id, self.ctx.chat_id, self.ctx.turn_id, self.ctx.bot_id
                )
            except OpsError as refused:
                block.error = str(refused)
                block.seconds = time.monotonic() - block.started_at
                self._finished(block)
                return
            block.machine = machine.alias or machine.name
            try:
                result = await channel.run_python(
                    machine.name,
                    block.code,
                    user_id=self.ctx.user_id,
                    turn_id=self.ctx.turn_id,
                    timeout=settings.pool_block_timeout,
                )
            except Exception as broken:  # noqa: BLE001 - the model must see what happened
                block.error = f"{type(broken).__name__}: {broken}"
                block.seconds = time.monotonic() - block.started_at
                logger.exception("%s python %s could not run", self.ctx.prefix, block.index)
                self._finished(block)
                return
            body, found = markers.split(result.output)
            block.output = body
            block.exit_code = result.exit_code
            block.seconds = result.seconds
            block.truncated = result.truncated
            await self._decorate(block, found)
            self._finished(block)

    async def _decorate(self, block: Block, found: list[markers.Block]) -> None:
        for item in found:
            if item.kind == markers.BlockKind.SENT:
                block.sent = True
            elif item.kind == markers.BlockKind.IMAGE:
                rendered = await self._image(item)
                if rendered is not None:
                    block.images.append(rendered)
            elif item.kind in (markers.BlockKind.NOTE, markers.BlockKind.PROGRESS):
                live.emit(self.ctx.turn_id, "note", text=str(item.data.get("text") or ""))
            elif item.kind == markers.BlockKind.LINK:
                block.output += f"\n{item.data.get('title') or 'link'}: {item.data.get('url')}"
            elif item.kind == markers.BlockKind.RESULT:
                block.output += f"\nresult: {item.data.get('value')}"
            elif item.kind == markers.BlockKind.ERROR:
                block.output += f"\nerror: {item.data.get('message')}"

    async def _image(self, item: markers.Block) -> dict | None:
        key = str(item.data.get("blob") or "")
        if not key:
            return None
        data = await blobs.get(self.ctx.user_id, key)
        if data is None:
            return None
        mime = str(item.data.get("mime") or sniff_mime(data, key))
        if image_problem(data, mime):
            return None
        live.emit(self.ctx.turn_id, "note", text=f"image {key} ({human_size(len(data))})")
        return image_block(data, mime)

    def _finished(self, block: Block) -> None:
        result = {
            "content": [{"type": "text", "text": short(block.heading() + "\n" + block.output, 8000)}]
        }
        if block.error or not block.ok:
            result["is_error"] = True
        self.recorder.tool_finished(block.call_id, TOOL, result, block.seconds * 1000)
        logger.info(
            "%s python %s on %s: %s",
            self.ctx.prefix,
            block.index,
            block.machine or "-",
            block.error or f"exit={block.exit_code} in {block.seconds:.1f}s",
        )

    async def settle(self) -> list[dict]:
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        return self.content()

    def content(self) -> list[dict]:
        """One tool_result per call, in the order the model asked for them."""
        out: list[dict] = []
        for block in self.blocks:
            text = block.heading()
            if block.truncated:
                text += f" (output cut at {human_size(settings.pool_max_output)})"
            body: list[dict] = [{"type": "text", "text": f"{text}\n{block.output.strip() or '(no output)'}"}]
            body.extend(block.images)
            result: dict = {
                "type": "tool_result",
                "tool_use_id": block.call_id,
                "content": body,
            }
            if block.error or not block.ok:
                result["is_error"] = True
            out.append(result)
        return out

    @property
    def replied(self) -> bool:
        return any(block.sent for block in self.blocks)
