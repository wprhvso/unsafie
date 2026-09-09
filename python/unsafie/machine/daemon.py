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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from unsafie_wire import channel as wire

USER_AGENT = "unsafie-machine"
FLUSH = 0.2
READ_SIZE = 65536
RETRY_MIN = 1.0


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


class Daemon:
    def __init__(self, link: Link, workdir: Path | None = None) -> None:
        self.link = link
        self.workdir = workdir or Path.home() / "work"
        self.name = ""
        self.poll_timeout = 25.0
        self.beat = 20.0
        self.outbox: queue.Queue[dict] = queue.Queue()
        self.stop = threading.Event()
        self.lease: dict[str, Any] = {}

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
        boot = None
        if started:
            try:
                boot = max(0.0, time.time() - float(started))
            except ValueError:
                pass
        run_id = os.environ.get("GITHUB_RUN_ID")
        answer = self.link.call(
            "POST",
            "/machines/register",
            body={
                "run_id": int(run_id) if run_id and run_id.isdigit() else None,
                "facts": self.facts(),
                "boot_seconds": boot,
            },
            worker=True,
            timeout=30.0,
        )
        self.name = str(answer["machine"])
        self.link.token = str(answer["token"])
        self.workdir.mkdir(parents=True, exist_ok=True)

    def serve(self) -> int:
        try:
            self.register()
        except Exception as e:
            sys.stderr.write(f"registration failed: {e}\n")
            return 0
        threading.Thread(target=self._sender, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()
        try:
            self._loop()
        finally:
            self.stop.set()
        return 0

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                answer = self.link.call(
                    "GET",
                    f"/machines/{self.name}/commands",
                    params={"wait": self.poll_timeout},
                    timeout=self.poll_timeout + 30.0,
                )
            except Exception:
                time.sleep(RETRY_MIN)
                continue
            for raw in (answer or {}).get("frames", []):
                self._dispatch(raw)

    def _dispatch(self, raw: dict) -> None:
        kind = str(raw.get("kind") or "")
        if kind in (wire.FrameKind.COMMAND, wire.FrameKind.PYTHON):
            if raw.get("tunnel"):
                from unsafie.machine.tunnel import serve_tunnel
                channel_id = str(raw["tunnel"].get("channel") or "")
                port = int(raw["tunnel"].get("port") or 0)
                kind_t = str(raw["tunnel"].get("kind") or "vnc")
                base = self.link.base.replace("https://", "wss://").replace("http://", "ws://")
                url = f"{base}/api/v1/machines/{self.name}/tunnel/{channel_id}?token={self.link.token}"
                threading.Thread(target=serve_tunnel, args=(url, kind_t, port), daemon=True).start()
                return
            threading.Thread(target=self._execute, args=(raw,), daemon=True).start()
        elif kind == wire.FrameKind.ASSIGN:
            self.lease = {
                "token": str(raw.get("token") or ""),
                "chat": raw.get("chat"),
                "turn": raw.get("turn") or "",
            }
            if self.lease["token"]:
                os.environ["UNSAFIE_TOKEN"] = self.lease["token"]
            if self.lease["chat"]:
                os.environ["UNSAFIE_CHAT"] = str(self.lease["chat"])
            if self.lease["turn"]:
                os.environ["UNSAFIE_TURN"] = str(self.lease["turn"])
            os.environ["UNSAFIE_API"] = self.link.base
            if self.lease["token"]:
                try:
                    from unsafie.cli.client import Client
                    from unsafie.machine import keys

                    keys.install(cli=Client(api=self.link.base, token=self.lease["token"]))
                except Exception as e:
                    sys.stderr.write(f"failed to install ssh keys: {e}\n")
                try:
                    from unsafie.cli import github

                    github.use(None)
                except Exception:
                    pass
        elif kind == wire.FrameKind.SHUTDOWN:
            self.stop.set()

    def _execute(self, raw: dict) -> None:
        cmd_id = str(raw.get("id") or "")
        cmd = str(raw.get("command") or raw.get("code") or "")
        if not cmd_id or not cmd:
            return
        started = time.monotonic()
        bash_bin = shutil.which("bash") or "/bin/bash"
        limit = float(raw.get("timeout") or 600.0)
        proc = None
        try:
            proc = subprocess.Popen(
                [bash_bin, "-lc", cmd],
                cwd=str(self.workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            out, _ = proc.communicate(timeout=limit)
            text = out.decode(errors="replace")
            self.outbox.put({"kind": str(wire.FrameKind.OUTPUT), "id": cmd_id, "stream": "out", "data": text})
            self.outbox.put({"kind": str(wire.FrameKind.EXIT), "id": cmd_id, "code": proc.returncode, "seconds": time.monotonic() - started})
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
                try:
                    out, _ = proc.communicate(timeout=2.0)
                    text = out.decode(errors="replace") if out else ""
                    if text:
                        self.outbox.put({"kind": str(wire.FrameKind.OUTPUT), "id": cmd_id, "stream": "out", "data": text})
                except Exception:
                    pass
            self.outbox.put({"kind": str(wire.FrameKind.OUTPUT), "id": cmd_id, "stream": "out", "data": f"\n[command timed out after {limit:.0f}s]\n"})
            self.outbox.put({"kind": str(wire.FrameKind.EXIT), "id": cmd_id, "code": 124, "seconds": time.monotonic() - started})
        except Exception as e:
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            self.outbox.put({"kind": str(wire.FrameKind.OUTPUT), "id": cmd_id, "stream": "out", "data": str(e)})
            self.outbox.put({"kind": str(wire.FrameKind.EXIT), "id": cmd_id, "code": 1, "seconds": time.monotonic() - started})
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass

    def _sender(self) -> None:
        while not self.stop.is_set():
            batch = []
            try:
                batch.append(self.outbox.get(timeout=FLUSH))
            except queue.Empty:
                continue
            while len(batch) < 32:
                try:
                    batch.append(self.outbox.get_nowait())
                except queue.Empty:
                    break
            try:
                self.link.call("POST", f"/machines/{self.name}/output", body={"frames": batch})
            except Exception:
                pass

    def _heartbeat(self) -> None:
        while not self.stop.wait(self.beat):
            try:
                self.link.call("POST", f"/machines/{self.name}/heartbeat", body={})
            except Exception:
                pass


def serve(api: str, worker_token: str) -> int:
    return Daemon(Link(api, worker_token)).serve()
