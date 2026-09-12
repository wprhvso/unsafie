import asyncio
import time
from dataclasses import dataclass, field

from unsafie.agent import live
from unsafie.agent.session import Ctx
from unsafie.log import get_logger, short
from unsafie.mime import human_size, image_block, image_problem, sniff_mime
from unsafie.pool import blobs, channel
from unsafie.settings import settings
from unsafie_wire import markers

logger = get_logger(__name__)

REASON_LIMIT = 300


@dataclass
class Block:
    index: int
    code: str
    started_at: float = field(default_factory=time.monotonic)
    machine: str = "pool"
    exit_code: int | None = None
    output: str = ""
    seconds: float = 0.0
    truncated: bool = False
    error: str | None = None
    images: list[dict] = field(default_factory=list)
    sent: bool = False
    stopped: bool = False
    spool_dir: str | None = None

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
        where = self.machine or "pool"
        if self.error:
            return f"[block {self.index}] {where}: {self.error}"
        if self.exit_code is None:
            return f"[block {self.index}] {where}: never came back, {self.seconds:.0f}s"
        if self.ok:
            return f"[block {self.index}] {where} · ok in {self.seconds:.1f}s"
        tail = self.reason()
        head = f"[block {self.index}] {where} · exit {self.exit_code} in {self.seconds:.1f}s"
        return f"{head}: {tail}" if tail else head


class Runner:
    def __init__(self, ctx: Ctx, recorder) -> None:
        self.ctx = ctx
        self.recorder = recorder
        self.blocks: list[Block] = []

    @property
    def count(self) -> int:
        return len(self.blocks)

    @property
    def stopped(self) -> bool:
        return any(block.stopped for block in self.blocks)

    @property
    def replied(self) -> bool:
        return any(block.sent for block in self.blocks)

    async def run(self, code: str, index: int | None = None) -> Block:
        if index is None:
            index = len(self.blocks) + 1
        block = Block(index=index, code=code, machine=self.ctx.machine_name or "pool")
        self.blocks.append(block)
        self.recorder.code_started(index, code, block.machine)
        await self._run(block)
        return block

    async def resume(self, index: int, code: str) -> Block:
        return await self.run(code, index=index)

    async def _run(self, block: Block) -> None:
        if self.stopped:
            block.error = "turn stopped"
            block.seconds = time.monotonic() - block.started_at
            self._finished(block)
            return

        if not self.ctx.machine_name:
            block.error = "no runner available for this chat"
            block.exit_code = 1
            block.seconds = time.monotonic() - block.started_at
            self._finished(block)
            return

        started = time.monotonic()
        try:
            result = await channel.run(
                self.ctx.machine_name,
                block.code,
                user_id=self.ctx.user_id,
                turn_id=self.ctx.turn_id,
                timeout=settings.agent_block_timeout,
            )
            block.exit_code = result.exit_code
            block.seconds = result.seconds
            block.truncated = result.truncated

            if result.exit_code == 124:
                block.error = f"command timed out after {settings.agent_block_timeout:.0f}s"
            elif result.exit_code == 137:
                block.error = f"runner {self.ctx.machine_name} disconnected"

            combined = result.output or ""
            body, found = markers.split(combined)
            block.output = body
            await self._decorate(block, found)
        except asyncio.CancelledError:
            block.error = "stopped by the user"
            block.seconds = time.monotonic() - started
            self._finished(block)
            raise
        except Exception as e:
            block.error = f"{type(e).__name__}: {e}"
            block.seconds = time.monotonic() - started
            logger.exception("%s runner error on %s", self.ctx.prefix, self.ctx.machine_name)
        finally:
            self._finished(block)

    async def _decorate(self, block: Block, found: list[markers.Block]) -> None:
        for item in found:
            if item.kind == markers.BlockKind.SENT:
                block.sent = True
            elif item.kind == markers.BlockKind.STOP:
                block.stopped = True
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
            elif item.kind == markers.BlockKind.LLM_START:
                live.emit(
                    self.ctx.turn_id,
                    "llm.start",
                    id=item.data.get("id"),
                    model=item.data.get("model"),
                )
            elif item.kind == markers.BlockKind.LLM_THOUGHT:
                live.emit(
                    self.ctx.turn_id,
                    "llm.thought",
                    id=item.data.get("id"),
                    text=item.data.get("text"),
                )
            elif item.kind == markers.BlockKind.LLM_DELTA:
                live.emit(
                    self.ctx.turn_id,
                    "llm.delta",
                    id=item.data.get("id"),
                    text=item.data.get("text"),
                )
            elif item.kind == markers.BlockKind.LLM_END:
                live.emit(
                    self.ctx.turn_id,
                    "llm.end",
                    id=item.data.get("id"),
                    usage=item.data.get("usage"),
                )

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
            machine=block.machine,
            exit_code=block.exit_code,
            output=self._body(block, limit=8000),
            seconds=block.seconds,
            error=block.error,
            images=block.images,
        )
        logger.info(
            "%s block %s on %s: %s",
            self.ctx.prefix,
            block.index,
            block.machine,
            block.error or f"exit={block.exit_code} in {block.seconds:.1f}s",
        )

    def content(self) -> list[dict]:
        if not self.blocks:
            return []
        parts: list[dict] = []
        for block in self.blocks:
            parts.append({"type": "text", "text": self._body(block)})
            if not block.failed and block.images:
                parts.extend(block.images)
        return parts

    async def settle(self) -> list[dict]:
        return self.content()
