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

NAG_EVERY = 60.0
REASON_LIMIT = 300


@dataclass
class Block:
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
    stopped: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def failed(self) -> bool:
        return bool(self.error) or not self.ok

    def reason(self) -> str:
        if self.error:
            return self.error[:REASON_LIMIT]
        lines = [line for line in (self.output or "").strip().splitlines() if line.strip()]
        return lines[-1][:REASON_LIMIT] if lines else ""

    def heading(self) -> str:
        where = self.machine or "no machine"
        if self.error:
            return f"[block {self.index}] {where}: {self.error}"
        if self.exit_code is None:
            return f"[block {self.index}] {where}: never came back, {self.seconds:.0f}s"
        if self.ok:
            return f"[block {self.index}] {where} · ok in {self.seconds:.1f}s"
        tail = self.reason()
        head = f"[block {self.index}] {where} · raised in {self.seconds:.1f}s"
        return f"{head}: {tail}" if tail else head


class Runner:
    def __init__(self, ctx: Ctx, recorder) -> None:
        self.ctx = ctx
        self.recorder = recorder
        self.blocks: list[Block] = []
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    @property
    def count(self) -> int:
        return len(self.blocks)

    @property
    def stopped(self) -> bool:
        return any(block.stopped for block in self.blocks)

    def start(self, code: str) -> Block:
        index = len(self.blocks) + 1
        block = Block(index=index, code=code)
        self.blocks.append(block)
        self.recorder.code_started(index, code)
        task = asyncio.create_task(
            self._run(block), name=f"python:{self.ctx.turn_id}:{block.index}"
        )
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return block

    async def _nag(self, block: Block) -> None:
        waited = 0.0
        while True:
            await asyncio.sleep(NAG_EVERY)
            waited += NAG_EVERY
            logger.warning(
                "%s python block %s on %s has been running for %.0fs",
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
            if self.stopped:
                block.error = "turn stopped"
                block.seconds = time.monotonic() - block.started_at
                self._finished(block)
                return
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
            except Exception as broken:
                block.error = f"{type(broken).__name__}: {broken}"
                block.seconds = time.monotonic() - block.started_at
                logger.exception("%s python block %s could not run", self.ctx.prefix, block.index)
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
            elif item.kind == markers.BlockKind.STOP:
                block.stopped = True
                block.sent = True
                live.emit(
                    self.ctx.turn_id,
                    "note",
                    name="unsafie.turn_stopped",
                    attributes={"index": block.index, "message": item.data.get("message")},
                )
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

    def _body(self, block: Block, limit: int | None = None) -> str:
        text = block.heading()
        if block.truncated:
            text += f" (output cut at {human_size(settings.pool_max_output)})"
        text = f"{text}\n{block.output.strip() or '(no output)'}"
        if limit:
            text = short(text, limit)
        return text

    def _finished(self, block: Block) -> None:
        self.recorder.code_finished(
            index=block.index,
            machine=block.machine or "-",
            exit_code=block.exit_code,
            output=self._body(block, limit=8000),
            seconds=block.seconds,
            error=block.error,
            images=block.images,
        )
        logger.info(
            "%s python block %s on %s: %s",
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
        if not self.blocks:
            return []
        parts: list[dict] = []
        for block in self.blocks:
            parts.append({"type": "text", "text": self._body(block)})
            if not block.failed and block.images:
                parts.extend(block.images)
        return parts

    @property
    def replied(self) -> bool:
        return any(block.sent for block in self.blocks)
