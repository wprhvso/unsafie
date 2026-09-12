import asyncio
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
from unsafie.pool import blobs
from unsafie.settings import settings
from unsafie_wire import markers

logger = logging.getLogger(__name__)

REASON_LIMIT = 300


@dataclass
class Block:
    index: int
    code: str
    started_at: float = field(default_factory=time.monotonic)
    machine: str = "sandbox"
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
        where = self.machine or "sandbox"
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
                hours=24.0,
            )
        return self._cli_token

    async def run(self, code: str, index: int | None = None) -> Block:
        if index is None:
            index = len(self.blocks) + 1
        block = Block(index=index, code=code, machine="sandbox")
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

        token = await self._ensure_token()
        started = time.monotonic()

        chat_base = Path(settings.chats_dir) / str(self.ctx.chat_id)
        workdir = chat_base / "work"
        homedir = chat_base / "home"
        workdir.mkdir(parents=True, exist_ok=True)
        homedir.mkdir(parents=True, exist_ok=True)

        argv: list[str] = []
        if shutil.which("nice"):
            argv.extend(["nice", "-n", "10"])
        if shutil.which("prlimit"):
            argv.extend(["prlimit", "--nproc=256"])

        bwrap_bin = shutil.which("bwrap")
        if not bwrap_bin:
            block.error = "bwrap binary not found"
            block.exit_code = 127
            block.seconds = time.monotonic() - started
            self._finished(block)
            return

        api_url = settings.public_base_url or f"http://127.0.0.1:{settings.port}"

        venv_dir = str(Path(sys.prefix).resolve())
        py_bin_dir = str(Path(sys.executable).resolve().parent)
        base_py_dir = str(Path(sys.base_prefix).resolve())

        py_module_dir = str(Path(__file__).resolve().parents[2])
        repo_root_dir = str(Path(__file__).resolve().parents[3])
        wire_module_dir = str(Path(py_module_dir) / "unsafie-wire" / "src")

        path_elements = [
            f"{venv_dir}/bin",
            py_bin_dir,
            str(Path.home() / ".local" / "bin"),
            str(Path.home() / ".cargo" / "bin"),
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/opt/homebrew/bin",
        ]
        path_env = ":".join(dict.fromkeys(p for p in path_elements if p))

        pythonpath_elements = [
            py_module_dir,
            wire_module_dir,
            os.environ.get("PYTHONPATH", ""),
        ]
        pythonpath_env = ":".join(dict.fromkeys(p for p in pythonpath_elements if p))

        resolv_path = Path("/etc/resolv.conf")
        real_resolv = str(resolv_path.resolve()) if resolv_path.exists() else "/etc/resolv.conf"

        argv.extend([
            bwrap_bin,
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/sbin", "/sbin",
            "--ro-bind", "/etc", "/etc",
            "--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve",
            "--ro-bind-try", real_resolv, "/etc/resolv.conf",
            "--ro-bind-try", "/opt", "/opt",
            "--ro-bind-try", venv_dir, venv_dir,
            "--ro-bind-try", base_py_dir, base_py_dir,
            "--ro-bind-try", py_module_dir, py_module_dir,
            "--ro-bind-try", repo_root_dir, repo_root_dir,
            "--ro-bind-try", str(Path.home() / ".python"), str(Path.home() / ".python"),
            "--ro-bind-try", str(Path.home() / ".local"), str(Path.home() / ".local"),
            "--ro-bind", "/proc", "/proc",
            "--dev-bind", "/dev", "/dev",
            "--tmpfs", "/tmp",
            "--bind", str(workdir), "/work",
            "--bind", str(homedir), "/home/unsafie",
            "--setenv", "HOME", "/home/unsafie",
            "--setenv", "PATH", path_env,
            "--setenv", "PYTHONPATH", pythonpath_env,
            "--setenv", "UNSAFIE_API", api_url,
            "--setenv", "UNSAFIE_TOKEN", token,
            "--setenv", "UNSAFIE_CHAT", str(self.ctx.chat_id),
            "--setenv", "UNSAFIE_TURN", str(self.ctx.turn_id),
            "--die-with-parent",
            "--chdir", "/work",
            "bash", "-lc", block.code,
        ])

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            block.exit_code = proc.returncode
            block.seconds = time.monotonic() - started

            combined = (out or b"").decode("utf-8", "replace")
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
            logger.exception("%s sandbox error", self.ctx.prefix)
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
