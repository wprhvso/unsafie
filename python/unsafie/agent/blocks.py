import asyncio
import contextlib
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
NAG_EVERY = 60.0
REASON_LIMIT = 300


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

    @property
    def failed(self) -> bool:
        return bool(self.error) or not self.ok

    def reason(self) -> str:
        """The one line that says what went wrong: the last line of the traceback."""
        if self.error:
            return self.error[:REASON_LIMIT]
        lines = [line for line in (self.output or "").strip().splitlines() if line.strip()]
        return lines[-1][:REASON_LIMIT] if lines else ""

    def heading(self) -> str:
        where = self.machine or "no machine"
        if self.error:
            return f"[{self.index}] {where}: {self.error}"
        if self.exit_code is None:
            return f"[{self.index}] {where}: never came back, {self.seconds:.0f}s"
        if self.ok:
            return f"[{self.index}] {where} · ok in {self.seconds:.1f}s"
        tail = self.reason()
        head = f"[{self.index}] {where} · raised in {self.seconds:.1f}s"
        return f"{head}: {tail}" if tail else head


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

    async def _nag(self, block: Block) -> None:
        """A block that says nothing for a minute is worth a line in the live log."""
        waited = 0.0
        while True:
            await asyncio.sleep(NAG_EVERY)
            waited += NAG_EVERY
            logger.warning(
                "%s python %s on %s has been running for %.0fs",
                self.ctx.prefix,
                block.index,
                block.machine or "-",
                waited,
            )
            live.emit(
                self.ctx.turn_id,
                "note",
                name="unsafie.block_slow",
                attributes={
                    "index": block.index,
                    "machine": block.machine,
                    "seconds": int(waited),
                    "timeout": settings.pool_block_timeout,
                },
            )

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
            watch = asyncio.create_task(
                self._nag(block), name=f"python-slow:{self.ctx.turn_id}:{block.index}"
            )
            try:
                result = await channel.run_python(
                    machine.name,
                    block.code,
                    user_id=self.ctx.user_id,
                    turn_id=self.ctx.turn_id,
                    timeout=settings.pool_block_timeout,
                )
            except asyncio.CancelledError:
                block.error = "stopped by the user"
                block.seconds = time.monotonic() - block.started_at
                self._finished(block)
                raise
            except Exception as broken:  # noqa: BLE001 - the model must see what happened
                block.error = f"{type(broken).__name__}: {broken}"
                block.seconds = time.monotonic() - block.started_at
                logger.exception("%s python %s could not run", self.ctx.prefix, block.index)
                self._finished(block)
                return
            finally:
                watch.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watch
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
                rendered = await self._image(block, item)
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

    async def _image(self, block: Block, item: markers.Block) -> dict | None:
        key = str(item.data.get("blob") or "")
        if not key:
            return None
        data = await blobs.get(self.ctx.user_id, key)
        if data is None:
            block.output += f"\n[image {key} was not stored, nothing to show]"
            return None
        mime = str(item.data.get("mime") or sniff_mime(data, key))
        problem = image_problem(data, mime)
        if problem:
            block.output += f"\n[image {key} not attached: {problem}]"
            return None
        live.emit(self.ctx.turn_id, "note", text=f"image {key} ({human_size(len(data))})")
        return image_block(data, mime)

    def _body(self, block: Block, limit: int | None = None) -> list[dict]:
        """The blocks of one tool_result.

        The API refuses a tool_result that carries anything but text when is_error is
        set, so a failed block never gets its pictures: it says where they went instead.
        """
        text = block.heading()
        if block.truncated:
            text += f" (output cut at {human_size(settings.pool_max_output)})"
        text = f"{text}\n{block.output.strip() or '(no output)'}"
        if limit:
            text = short(text, limit)
        body: list[dict] = [{"type": "text", "text": text}]
        if not block.images:
            return body
        if block.failed:
            body[0]["text"] += (
                f"\n[{len(block.images)} image(s) not attached: a failed call may only carry "
                "text. The screenshot is stored — show it from a call that succeeds.]"
            )
            return body
        body.extend(block.images)
        return body

    def _finished(self, block: Block) -> None:
        result: dict = {"content": self._body(block, limit=8000)}
        if block.failed:
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
            result: dict = {
                "type": "tool_result",
                "tool_use_id": block.call_id,
                "content": self._body(block),
            }
            if block.failed:
                result["is_error"] = True
            out.append(result)
        return out

    @property
    def replied(self) -> bool:
        return any(block.sent for block in self.blocks)
