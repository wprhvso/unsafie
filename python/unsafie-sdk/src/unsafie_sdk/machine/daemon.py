import json
import os
import platform
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from unsafie_sdk.client import save as save_config
from unsafie_sdk.machine.repl import Repl, interrupt
from unsafie_wire import channel as wire

USER_AGENT = "unsafie-machine"
FLUSH = 0.2
READ_SIZE = 65536
RETRY_MIN = 1.0
RETRY_MAX = 15.0
KILL_GRACE = 5.0
TIMED_OUT = 124
CANCELLED = 125


def _log(message: str) -> None:
    sys.stderr.write(f"[machine] {message}\n")
    sys.stderr.flush()


class Link:
    def __init__(self, base: str, worker: str = "") -> None:
        self.base = base.rstrip("/")
        self.worker = worker
        self.token = ""

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float = 60.0,
        worker: bool = False,
    ) -> Any:
        url = f"{self.base}/api/v1{path}"
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(url, data=payload, method=method.upper())
        request.add_header("User-Agent", USER_AGENT)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        if worker:
            request.add_header("X-Unsafie-Worker", self.worker)
        elif self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            raw = answer.read()
        return json.loads(raw) if raw else None

    def patient(self, method: str, path: str, **kwargs: Any) -> Any:
        delay = RETRY_MIN
        while True:
            try:
                return self.call(method, path, **kwargs)
            except urllib.error.HTTPError as refused:
                if refused.code < 500 and refused.code != 429:
                    raise
                _log(f"{path}: {refused.code}, retrying")
            except (urllib.error.URLError, TimeoutError, OSError) as unreachable:
                _log(f"{path}: {unreachable}, retrying")
            time.sleep(delay)
            delay = min(delay * 2, RETRY_MAX)


class Job:
    def __init__(self, command_id: str, process: subprocess.Popen) -> None:
        self.command_id = command_id
        self.process = process
        self.started = time.monotonic()
        self.expired = False


class Daemon:
    def __init__(self, link: Link, profile: str = "fast", workdir: Path | None = None) -> None:
        self.link = link
        self.profile = profile
        self.workdir = workdir or Path.home() / "work"
        self.name = ""
        self.poll_timeout = 25.0
        self.beat = 20.0
        self.outbox: queue.Queue[dict] = queue.Queue()
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.lease: dict[str, Any] = {}
        self.reason = "exited"
        self.repl: Repl | None = None
        self.block_id = ""
        self.block_thread: threading.Thread | None = None
        self.blocks: queue.Queue[dict] = queue.Queue()

    # registration ---------------------------------------------------------

    def facts(self) -> dict[str, Any]:
        total, _, free = shutil.disk_usage("/")
        return {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpus": os.cpu_count(),
            "disk_gb": round(free / 1_000_000_000, 1),
            "disk_total_gb": round(total / 1_000_000_000, 1),
            "runner": os.environ.get("RUNNER_NAME") or "",
        }

    def register(self) -> None:
        started = os.environ.get("UNSAFIE_BOOT_STARTED")
        boot = max(0.0, time.time() - float(started)) if started and started.isdigit() else None
        run_id = os.environ.get("GITHUB_RUN_ID")
        answer = self.link.patient(
            "POST",
            "/machines/register",
            body={
                "run_id": int(run_id) if run_id and run_id.isdigit() else None,
                "profile": self.profile,
                "facts": self.facts(),
                "boot_seconds": boot,
            },
            worker=True,
            timeout=30.0,
        )
        self.name = str(answer["machine"])
        self.link.token = str(answer["token"])
        self.poll_timeout = float(answer.get("poll") or self.poll_timeout)
        self.beat = float(answer.get("heartbeat") or self.beat)
        self.workdir.mkdir(parents=True, exist_ok=True)
        _log(f"registered as {self.name}, booted in {boot if boot is None else round(boot, 1)}s")

    # lifecycle ------------------------------------------------------------

    def serve(self) -> int:
        self.register()
        crew = [
            threading.Thread(target=self._sender, name="sender", daemon=True),
            threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True),
            threading.Thread(target=self._blocks, name="repl", daemon=True),
        ]
        for thread in crew:
            thread.start()
        self._install_signals()
        try:
            self._loop()
        finally:
            self.stop.set()
            self._drain()
            self._say_gone()
        return 0

    def _install_signals(self) -> None:
        def handler(signum: int, _frame: Any) -> None:
            self.reason = f"signal {signum}"
            self.stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, handler)

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                answer = self.link.call(
                    "GET",
                    f"/machines/{self.name}/commands",
                    params={"wait": self.poll_timeout},
                    timeout=self.poll_timeout + 30.0,
                )
            except urllib.error.HTTPError as refused:
                if refused.code in (401, 410):
                    self.reason = "dropped by the server"
                    _log(f"the server let this machine go: {refused.code}")
                    return
                _log(f"poll: {refused.code}")
                time.sleep(RETRY_MIN)
                continue
            except (urllib.error.URLError, TimeoutError, OSError) as unreachable:
                _log(f"poll: {unreachable}")
                time.sleep(RETRY_MIN)
                continue
            for raw in (answer or {}).get("frames", []):
                self._dispatch(raw)

    def _dispatch(self, raw: dict) -> None:
        kind = str(raw.get("kind") or "")
        if kind == wire.FrameKind.PYTHON:
            self.blocks.put(raw)
            return
        if kind == wire.FrameKind.COMMAND:
            if raw.get("tunnel"):
                threading.Thread(target=self._tunnel, args=(raw["tunnel"],), daemon=True).start()
                return
            threading.Thread(target=self._execute, args=(raw,), daemon=True).start()
            return
        if kind == wire.FrameKind.ASSIGN:
            self._assign(raw)
            return
        if kind == wire.FrameKind.CANCEL:
            self._cancel(str(raw.get("id") or ""))
            return
        if kind == wire.FrameKind.SHUTDOWN:
            self.reason = str(raw.get("reason") or "released")
            _log(f"shutting down: {self.reason}")
            self.stop.set()

    # the lease ------------------------------------------------------------

    def _assign(self, raw: dict) -> None:
        self.lease = {
            "token": str(raw.get("token") or ""),
            "chat": raw.get("chat"),
            "user": raw.get("user"),
            "alias": raw.get("alias") or "",
            "turn": raw.get("turn") or "",
        }
        for name, value in self._environment().items():
            os.environ[name] = value
        save_config(
            {
                "token": self.lease["token"],
                "api": self.link.base,
                "chat": str(self.lease["chat"] or ""),
                "machine": self.name,
            }
        )
        self.repl = None
        self.blocks = queue.Queue()
        threading.Thread(target=self._settle, name="settle", daemon=True).start()
        _log(f"leased as {self.lease['alias'] or self.name}")

    def _settle(self) -> None:
        """Everything the owner expects to find on a machine of theirs."""
        try:
            from unsafie_sdk import ssh

            ssh.install()
            _log("the owner's ssh key is in place")
        except Exception as broken:  # noqa: BLE001 - a machine without a key still works
            _log(f"no ssh key on this machine: {broken}")
        for line in (
            ["git", "config", "--global", "user.name", "unsafie"],
            ["git", "config", "--global", "user.email", "agent@unsafie.com"],
            ["git", "config", "--global", "init.defaultBranch", "main"],
            ["git", "config", "--global", "--add", "safe.directory", "*"],
        ):
            subprocess.run(line, check=False, capture_output=True)

    def _environment(self) -> dict[str, str]:
        env = {"UNSAFIE_API": self.link.base, "UNSAFIE_MACHINE": self.name}
        if self.lease.get("token"):
            env["UNSAFIE_TOKEN"] = str(self.lease["token"])
        if self.lease.get("chat") is not None:
            env["UNSAFIE_CHAT"] = str(self.lease["chat"])
        if self.lease.get("turn"):
            env["UNSAFIE_TURN"] = str(self.lease["turn"])
        if self.lease.get("alias"):
            env["UNSAFIE_ALIAS"] = str(self.lease["alias"])
        return env

    # python blocks --------------------------------------------------------

    def _repl(self) -> Repl:
        if self.repl is None:
            self.repl = Repl(sink=lambda text: self._emit(wire.output(self.block_id, text)))
        return self.repl

    def _blocks(self) -> None:
        while not self.stop.is_set():
            try:
                frame = self.blocks.get(timeout=FLUSH)
            except queue.Empty:
                continue
            self._run_block(frame)

    def _run_block(self, frame: dict) -> None:
        block_id = str(frame.get("id") or "")
        code = str(frame.get("code") or "")
        if not block_id or not code.strip():
            return
        repl = self._repl()
        if frame.get("reset"):
            repl.reset()
        self.block_id = block_id
        self.block_thread = threading.current_thread()
        outcome = repl.run(code, frame.get("timeout"))
        self.block_thread = None
        self._emit(wire.exited(block_id, 0 if outcome.ok else 1, outcome.seconds))

    # shell ----------------------------------------------------------------

    def _execute(self, raw: dict) -> None:
        command_id = str(raw.get("id") or "")
        command = str(raw.get("command") or "")
        if not command_id or not command:
            return
        cwd = Path(str(raw.get("cwd") or self.workdir)).expanduser()
        if not cwd.is_dir():
            cwd = self.workdir
        timeout = float(raw.get("timeout") or 0) or None
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                ["/bin/bash", "-lc", command],
                cwd=str(cwd),
                env=dict(os.environ, **self._environment()),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as broken:
            self._emit(wire.output(command_id, f"cannot start the command: {broken}\n"))
            self._emit(wire.exited(command_id, 127, time.monotonic() - started))
            return
        with self.lock:
            self.jobs[command_id] = Job(command_id, process)
        if process.stdin is not None:
            try:
                if raw.get("stdin"):
                    process.stdin.write(str(raw["stdin"]).encode())
                process.stdin.close()
            except OSError:
                pass
        watchdog = None
        if timeout:
            watchdog = threading.Timer(timeout, self._expire, args=(command_id,))
            watchdog.daemon = True
            watchdog.start()
        code = self._pump(command_id, process)
        if watchdog is not None:
            watchdog.cancel()
        with self.lock:
            job = self.jobs.pop(command_id, None)
        if job is not None and job.expired:
            code = TIMED_OUT
        self._emit(wire.exited(command_id, code, time.monotonic() - started))

    def _pump(self, command_id: str, process: subprocess.Popen) -> int:
        stream = process.stdout
        if stream is not None:
            reader = getattr(stream, "read1", stream.read)
            while True:
                chunk = reader(READ_SIZE)
                if not chunk:
                    break
                self._emit(wire.output(command_id, chunk.decode(errors="replace")))
        return process.wait()

    def _expire(self, command_id: str) -> None:
        with self.lock:
            job = self.jobs.get(command_id)
        if job is None:
            return
        job.expired = True
        self._emit(wire.output(command_id, "\n[timeout] the command ran out of time\n"))
        self._kill(job)

    def _cancel(self, command_id: str) -> None:
        if command_id and command_id == self.block_id and self.block_thread is not None:
            self._emit(wire.output(command_id, "\n[cancelled]\n"))
            interrupt(self.block_thread)
            return
        with self.lock:
            job = self.jobs.get(command_id)
        if job is None:
            return
        self._emit(wire.output(command_id, "\n[cancelled]\n"))
        self._kill(job)

    def _kill(self, job: Job) -> None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(job.process.pid), sig)
            except (ProcessLookupError, PermissionError):
                return
            deadline = time.monotonic() + KILL_GRACE
            while time.monotonic() < deadline:
                if job.process.poll() is not None:
                    return
                time.sleep(0.1)

    # plumbing -------------------------------------------------------------

    def _tunnel(self, request: dict) -> None:
        from unsafie_sdk.machine.tunnel import serve_tunnel

        channel_id = str(request.get("channel") or "")
        kind = str(request.get("kind") or "vnc")
        port = int(request.get("port") or 0)
        base = self.link.base.replace("https://", "wss://").replace("http://", "ws://")
        url = f"{base}/api/v1/machines/{self.name}/tunnel/{channel_id}?token={self.link.token}"
        try:
            serve_tunnel(url, kind, port)
        except Exception as broken:  # noqa: BLE001 - a broken tunnel must not kill the machine
            _log(f"tunnel {kind}: {broken}")

    def _emit(self, frame: wire.Frame) -> None:
        self.outbox.put({"kind": str(frame.kind), "id": frame.id, **frame.body})

    def _sender(self) -> None:
        while not self.stop.is_set() or not self.outbox.empty():
            frames = self._collect()
            if not frames:
                time.sleep(FLUSH)
                continue
            self._post(frames)

    def _collect(self) -> list[dict]:
        frames: list[dict] = []
        try:
            frames.append(self.outbox.get(timeout=FLUSH))
        except queue.Empty:
            return frames
        while len(frames) < 64:
            try:
                frames.append(self.outbox.get_nowait())
            except queue.Empty:
                break
        return frames

    def _post(self, frames: list[dict]) -> None:
        try:
            self.link.call("POST", f"/machines/{self.name}/output", body={"frames": frames})
        except urllib.error.HTTPError as refused:
            if refused.code in (401, 410):
                self.stop.set()
                return
            _log(f"output: {refused.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as unreachable:
            _log(f"output: {unreachable}")

    def _drain(self) -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            frames = self._collect()
            if not frames:
                return
            self._post(frames)

    def _heartbeat(self) -> None:
        while not self.stop.wait(self.beat):
            try:
                self.link.call("POST", f"/machines/{self.name}/heartbeat", body={})
            except urllib.error.HTTPError as refused:
                if refused.code in (401, 410):
                    self.reason = "dropped by the server"
                    self.stop.set()
                    return
            except (urllib.error.URLError, TimeoutError, OSError):
                continue

    def _say_gone(self) -> None:
        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            self._kill(job)
        if not self.name:
            return
        try:
            self.link.call("POST", f"/machines/{self.name}/gone", params={"reason": self.reason})
        except Exception:  # noqa: BLE001 - we are leaving anyway
            pass
        _log(f"gone: {self.reason}")


def serve(api: str, worker_token: str, profile: str = "fast") -> int:
    return Daemon(Link(api, worker_token), profile).serve()
