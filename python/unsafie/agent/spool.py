import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

DEFAULT_SPOOL_ROOT = Path("/run/unsafie/spool")
FALLBACK_SPOOL_ROOT = Path("/tmp/unsafie-spool")


def _get_spool_base() -> Path:
    try:
        if DEFAULT_SPOOL_ROOT.exists():
            return DEFAULT_SPOOL_ROOT
        DEFAULT_SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
        return DEFAULT_SPOOL_ROOT
    except OSError:
        FALLBACK_SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
        return FALLBACK_SPOOL_ROOT


class SpoolStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    FINISHED = "finished"
    DEAD = "dead"


@dataclass(frozen=True)
class SpoolProbeResult:
    status: SpoolStatus
    pid: int | None
    pgid: int | None
    exit_code: int | None
    output: str
    started_at: float | None
    duration: float
    interrupted: bool


class BashSpool:
    def __init__(self, turn_id: UUID | str, step: int, base_dir: Path | None = None) -> None:
        self.turn_id = str(turn_id)
        self.step = step
        root = base_dir or _get_spool_base()
        self.dir = root / self.turn_id / f"step_{step}"
        self.script_file = self.dir / "run.sh"
        self.stdout_file = self.dir / "stdout.log"
        self.meta_file = self.dir / "meta.json"
        self.exit_code_file = self.dir / "exit_code"
        self._waiter: asyncio.Task | None = None

    def prepare(self, code: str, cwd: str | Path | None = None) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self.dir.chmod(0o700)
        except OSError:
            pass

        script_body = ["#!/usr/bin/env bash"]
        if cwd:
            script_body.append(f"cd {Path(cwd).resolve()}")
        script_body.append(code.strip())
        script_body.append("")

        self.script_file.write_text("\n".join(script_body), encoding="utf-8")
        try:
            self.script_file.chmod(0o700)
        except OSError:
            pass

        if not self.stdout_file.exists():
            self.stdout_file.touch(mode=0o600)

        return self.dir

    async def launch(
        self,
        bash_bin: str = "/bin/bash",
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> int:
        out_fd = os.open(self.stdout_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            proc = await asyncio.create_subprocess_exec(
                bash_bin,
                str(self.script_file),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=out_fd,
                stderr=out_fd,
                env=env,
                cwd=str(cwd) if cwd else None,
                start_new_session=True,
            )
        finally:
            os.close(out_fd)

        pid = proc.pid
        pgid = proc.pid
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pass

        meta = {
            "pid": pid,
            "pgid": pgid,
            "turn_id": self.turn_id,
            "step": self.step,
            "started_at": time.time(),
        }
        self.meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        self._waiter = asyncio.create_task(self._watch_proc(proc))
        return pid

    async def _watch_proc(self, proc: asyncio.subprocess.Process) -> None:
        exit_code = await proc.wait()
        self.exit_code_file.write_text(f"{exit_code}\n", encoding="utf-8")

    def probe(self) -> SpoolProbeResult:
        if not self.meta_file.is_file():
            return SpoolProbeResult(
                status=SpoolStatus.PENDING,
                pid=None,
                pgid=None,
                exit_code=None,
                output="",
                started_at=None,
                duration=0.0,
                interrupted=False,
            )

        try:
            meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

        pid = meta.get("pid")
        pgid = meta.get("pgid", pid)
        started_at = meta.get("started_at")

        if self.exit_code_file.is_file():
            try:
                exit_code = int(self.exit_code_file.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                exit_code = 0
            output = self.read_output()
            mtime = self.exit_code_file.stat().st_mtime
            duration = max(0.0, mtime - started_at) if started_at else 0.0
            return SpoolProbeResult(
                status=SpoolStatus.FINISHED,
                pid=pid,
                pgid=pgid,
                exit_code=exit_code,
                output=output,
                started_at=started_at,
                duration=duration,
                interrupted=False,
            )

        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False

        output = self.read_output()
        now = time.time()
        duration = max(0.0, now - started_at) if started_at else 0.0

        if alive:
            return SpoolProbeResult(
                status=SpoolStatus.RUNNING,
                pid=pid,
                pgid=pgid,
                exit_code=None,
                output=output,
                started_at=started_at,
                duration=duration,
                interrupted=False,
            )

        return SpoolProbeResult(
            status=SpoolStatus.DEAD,
            pid=pid,
            pgid=pgid,
            exit_code=137,
            output=output,
            started_at=started_at,
            duration=duration,
            interrupted=True,
        )

    def read_output(self, limit: int | None = None) -> str:
        if not self.stdout_file.is_file():
            return ""
        try:
            size = self.stdout_file.stat().st_size
            if limit and size > limit:
                with open(self.stdout_file, "rb") as f:
                    f.seek(size - limit)
                    raw = f.read()
            else:
                raw = self.stdout_file.read_bytes()
            return raw.decode("utf-8", "replace")
        except Exception:
            return ""

    def read_exit_code(self) -> int | None:
        if not self.exit_code_file.is_file():
            return None
        try:
            return int(self.exit_code_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None

    def is_alive(self) -> bool:
        probe = self.probe()
        return probe.status == SpoolStatus.RUNNING

    async def wait(self, timeout: float | None = None, poll_interval: float = 0.05) -> int:
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            probe = self.probe()
            if probe.status in (SpoolStatus.FINISHED, SpoolStatus.DEAD):
                return probe.exit_code if probe.exit_code is not None else 0
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"spool process did not finish within {timeout}s")
            await asyncio.sleep(poll_interval)

    async def tail(
        self, from_offset: int = 0, poll_interval: float = 0.1
    ) -> AsyncIterator[tuple[str, int]]:
        offset = from_offset
        while True:
            if self.stdout_file.is_file():
                size = self.stdout_file.stat().st_size
                if size > offset:
                    with open(self.stdout_file, "rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                    offset = size
                    yield chunk.decode("utf-8", "replace"), offset

            probe = self.probe()
            if probe.status in (SpoolStatus.FINISHED, SpoolStatus.DEAD):
                if self.stdout_file.is_file():
                    size = self.stdout_file.stat().st_size
                    if size > offset:
                        with open(self.stdout_file, "rb") as f:
                            f.seek(offset)
                            chunk = f.read(size - offset)
                        offset = size
                        yield chunk.decode("utf-8", "replace"), offset
                break

            await asyncio.sleep(poll_interval)

    def terminate(self, grace: float = 2.0) -> None:
        if not self.meta_file.is_file():
            return
        try:
            meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            return

        pgid = meta.get("pgid") or meta.get("pid")
        if not pgid:
            return

        with contextlib.suppress(OSError):
            os.killpg(pgid, signal.SIGTERM)

        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not self.is_alive():
                return
            time.sleep(0.05)

        with contextlib.suppress(OSError):
            os.killpg(pgid, signal.SIGKILL)

    def cleanup(self) -> None:
        if self._waiter and not self._waiter.done():
            self._waiter.cancel()
        shutil.rmtree(self.dir, ignore_errors=True)
