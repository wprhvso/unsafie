import asyncio
import contextlib
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from unsafie import tokens
from unsafie.agent import live
from unsafie.agent.session import Ctx
from unsafie.log import short
from unsafie.mime import human_size, image_block, image_problem, sniff_mime
from unsafie.gh import ensure_gh
from unsafie.pool import blobs
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
    machine: str = "local"
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
        where = self.machine or "local"
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
        self._cli_token: str | None = None

    @property
    def count(self) -> int:
        return len(self.blocks)

    @property
    def stopped(self) -> bool:
        return any(block.stopped for block in self.blocks)

    @property
    def replied(self) -> bool:
        return any(block.sent for block in self.blocks)

    async def _ensure_token(self) -> str:
        if self._cli_token is None:
            _, self._cli_token = await tokens.issue(
                user_id=self.ctx.user_id,
                bot_id=self.ctx.bot_id,
                chat_id=self.ctx.chat_id,
                name=f"agent-{self.ctx.turn_id}",
                hours=2.0,
            )
            await self._install_ssh_keys()
        return self._cli_token

    async def _install_ssh_keys(self) -> None:
        try:
            from unsafie.cli.client import Client
            from unsafie.machine import keys

            api = settings.public_base_url or f"http://{settings.host}:{settings.port}"
            await asyncio.to_thread(keys.install, cli=Client(api=api, token=self._cli_token))
        except Exception as e:
            logger.warning("%s failed to install ssh keys: %s", self.ctx.prefix, e)

    async def run(self, code: str) -> Block:
        index = len(self.blocks) + 1
        block = Block(index=index, code=code)
        self.blocks.append(block)
        self.recorder.code_started(index, code, "local")
        await self._run(block)
        return block

    async def _nag(self, block: Block) -> None:
        waited = 0.0
        while True:
            await asyncio.sleep(NAG_EVERY)
            waited += NAG_EVERY
            logger.warning(
                "%s bash block %s has been running for %.0fs",
                self.ctx.prefix,
                block.index,
                waited,
            )
            live.emit(
                self.ctx.turn_id,
                "note",
                name="unsafie.block_slow",
                attributes={
                    "index": block.index,
                    "machine": "local",
                    "seconds": int(waited),
                    "timeout": settings.agent_block_timeout,
                },
            )

    async def _run(self, block: Block) -> None:
        if self.stopped:
            block.error = "turn stopped"
            block.seconds = time.monotonic() - block.started_at
            self._finished(block)
            return
        token = await self._ensure_token()
        bash_bin = shutil.which("bash") or "/bin/bash"
        if not os.path.exists(bash_bin) and not shutil.which("bash"):
            block.error = "bash not available"
            block.exit_code = 127
            block.seconds = time.monotonic() - block.started_at
            self._finished(block)
            return

        gh_bin = None
        try:
            gh_bin = await ensure_gh()
        except Exception as e:
            logger.warning("%s failed to ensure gh: %s", self.ctx.prefix, e)

        env = dict(os.environ)
        extra_paths = [
            str(Path(sys.prefix) / "bin"),
            str(Path(sys.executable).parent),
            str(Path(gh_bin).parent) if gh_bin else "",
            str(Path.home() / ".cargo" / "bin"),
            str(Path.home() / ".local" / "bin"),
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]
        env["PATH"] = ":".join(p for p in extra_paths if p) + ":" + env.get("PATH", "")
        env["UNSAFIE_API"] = settings.public_base_url or f"http://{settings.host}:{settings.port}"
        env["UNSAFIE_TOKEN"] = token
        env["UNSAFIE_CHAT"] = str(self.ctx.chat_id)
        env["UNSAFIE_TURN"] = str(self.ctx.turn_id)
        if self.ctx.inline_message_id:
            env["UNSAFIE_INLINE_MESSAGE_ID"] = self.ctx.inline_message_id

        watch = asyncio.create_task(
            self._nag(block), name=f"bash-slow:{self.ctx.turn_id}:{block.index}"
        )
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                bash_bin,
                "-c",
                block.code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            raw_out, raw_err = await asyncio.wait_for(
                proc.communicate(),
                timeout=settings.agent_block_timeout,
            )
            combined = raw_out.decode("utf-8", "replace") + (
                "\n" + raw_err.decode("utf-8", "replace") if raw_err else ""
            )
            block.exit_code = proc.returncode
        except TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            block.error = f"command timed out after {settings.agent_block_timeout:.0f}s"
            block.exit_code = 124
            combined = ""
        except FileNotFoundError:
            block.error = "bash executable 'bash' not found"
            block.exit_code = 127
            combined = ""
        except asyncio.CancelledError:
            block.error = "stopped by the user"
            block.seconds = time.monotonic() - block.started_at
            self._finished(block)
            raise
        except Exception as broken:
            block.error = f"{type(broken).__name__}: {broken}"
            block.seconds = time.monotonic() - block.started_at
            logger.exception("%s bash block %s could not run", self.ctx.prefix, block.index)
            self._finished(block)
            return
        finally:
            watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch

        lines = combined.splitlines(keepends=True)
        if len(lines) > settings.pool_max_output_lines:
            combined = "".join(lines[: settings.pool_max_output_lines])
            block.truncated = True
        elif len(combined) > settings.pool_max_output:
            combined = combined[: settings.pool_max_output]
            block.truncated = True

        body, found = markers.split(combined)
        block.output = body
        block.seconds = time.monotonic() - started
        await self._decorate(block, found)
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
            machine="local",
            exit_code=block.exit_code,
            output=self._body(block, limit=8000),
            seconds=block.seconds,
            error=block.error,
            images=block.images,
        )
        logger.info(
            "%s bash block %s: %s",
            self.ctx.prefix,
            block.index,
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
