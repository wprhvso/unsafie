import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from unsafie_sdk.client import client, setting
from unsafie_sdk.errors import UnsafieError

FINAL = ("done", "failed", "lost", "cancelled")


def _turn() -> str | None:
    return os.environ.get("UNSAFIE_TURN") or None


@dataclass(frozen=True)
class Run:
    machine: str
    exit_code: int | None
    output: str
    seconds: float
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        return self.output

    def check(self) -> "Run":
        """Raise if the command failed; return itself otherwise."""
        if not self.ok:
            raise UnsafieError(f"exit={self.exit_code} on {self.machine}: {self.output.strip()[-400:]}")
        return self


@dataclass(frozen=True)
class Machine:
    name: str
    alias: str | None
    state: str
    facts: dict

    @property
    def id(self) -> str:
        return self.alias or self.name

    def run(self, command: str, **kwargs) -> Run:
        """Run a shell command on this machine."""
        return run(command, machine=self.id, **kwargs)

    def release(self) -> list[str]:
        """Give this machine back; it is destroyed."""
        return release(self.id)

    def rename(self, alias: str) -> dict:
        """Give the machine a human name."""
        return client().call("POST", "/pool/rename", {"machine": self.id, "alias": alias})


def _machine(row: dict) -> Machine:
    return Machine(
        name=row.get("name", ""),
        alias=row.get("alias"),
        state=row.get("state", ""),
        facts=row.get("facts") or {},
    )


def here() -> str | None:
    """The name of the machine this code runs on."""
    return setting("machine")


def listing() -> list[Machine]:
    """Machines currently leased to this account."""
    answer = client().call("GET", "/pool/machines")
    return [_machine(row) for row in answer.get("machines", [])]


def capacity() -> dict:
    """How many machines are idle, leased, on ci and alive in the pool."""
    return client().call("GET", "/pool/machines").get("capacity", {})


def take(count: int = 1, *, wait: float | None = None) -> list[Machine]:
    """Take machines from the pool. They are single use: releasing destroys them."""
    body = {"count": int(count), "wait": wait, "turn": _turn()}
    answer = client().call("POST", "/pool/take", body, timeout=(wait or 180) + 60)
    return [_machine(row) for row in answer.get("machines", [])]


def release(machine: str | Machine | None = None) -> list[str]:
    """Release a machine (or all of them) — the job ends and nothing survives on it."""
    name = machine.id if isinstance(machine, Machine) else machine
    return client().call("POST", "/pool/release", {"machine": name}).get("released", [])


def run(
    command: str,
    *,
    machine: str | Machine | None = None,
    timeout: float | None = None,
    cwd: str | None = None,
    stdin: str | None = None,
) -> Run:
    """Run a shell command on one of your machines and wait for it."""
    name = machine.id if isinstance(machine, Machine) else machine
    body = {
        "command": command,
        "machine": name,
        "timeout": timeout,
        "cwd": cwd,
        "stdin": stdin,
        "turn": _turn(),
    }
    answer = client().call("POST", "/pool/run", body, timeout=(timeout or 600) + 60)
    return Run(
        machine=str(answer.get("machine") or ""),
        exit_code=answer.get("exit_code"),
        output=str(answer.get("output") or ""),
        seconds=float(answer.get("seconds") or 0),
        truncated=bool(answer.get("truncated")),
    )


def fan(command: str, *, machines: list[str] | None = None, timeout: float | None = None):
    """Run the same command on every machine at once and collect the results."""
    names = machines or [m.id for m in listing()]
    if not names:
        raise UnsafieError("no machines to run on", "take some first: machines.take(3)")
    with ThreadPoolExecutor(max_workers=min(len(names), 16)) as crew:
        futures = {name: crew.submit(run, command, machine=name, timeout=timeout) for name in names}
        return {name: future.result() for name, future in futures.items()}


def submit(command: str, *, count: int = 1, machine: str | None = None, timeout=None) -> list[str]:
    """Start a command in the background and return job ids."""
    jobs: list[str] = []
    for _ in range(max(1, min(count, 20))):
        answer = client().call(
            "POST",
            "/pool/run",
            {
                "command": command,
                "machine": machine,
                "background": True,
                "timeout": timeout,
                "turn": _turn(),
            },
        )
        jobs.append(str(answer["job"]))
    return jobs


def jobs(limit: int = 20) -> list[dict]:
    """Background jobs of this account."""
    return client().call("GET", "/pool/jobs", params={"limit": limit}).get("jobs", [])


def logs(job: str, *, follow: bool = False, timeout: float = 600.0) -> str:
    """Read what a background job printed; follow waits for it to finish."""
    seen = 0
    collected: list[str] = []
    deadline = time.monotonic() + timeout
    while True:
        answer = client().call(
            "GET", f"/pool/jobs/{job}", params={"wait": 3 if follow else 0, "since": seen}
        )
        chunk = str(answer.get("output") or "")
        if chunk:
            collected.append(chunk)
        seen = int(answer.get("read") or seen)
        if not follow or answer.get("status") in FINAL or time.monotonic() > deadline:
            return "".join(collected)


def cancel(job: str) -> dict:
    """Stop a background job."""
    return client().call("POST", f"/pool/jobs/{job}/cancel", {})


def copy(source: str, target: str) -> dict:
    """Copy a file between machines: copy('box-1:/tmp/a', 'box-2:/tmp/a')."""
    from unsafie_sdk import store

    def split(reference: str) -> tuple[str | None, str]:
        name, sep, path = reference.partition(":")
        return (name, path) if sep and "/" not in name else (None, reference)

    source_machine, source_path = split(source)
    target_machine, target_path = split(target)
    key = f"copy/{int(time.time())}-{os.getpid()}"
    if source_machine:
        run(f"unsafie-machine put {key} {source_path}", machine=source_machine).check()
    else:
        store.put(key, open(source_path, "rb").read())
    if target_machine:
        run(f"unsafie-machine get {key} {target_path}", machine=target_machine).check()
    else:
        with open(target_path, "wb") as handle:
            handle.write(store.get(key))
    store.delete(key)
    return {"from": source, "to": target}


def desktop(machine: str | None = None) -> str:
    """A link to the live desktop of a machine, for the human to take the mouse."""
    answer = client().call("POST", "/pool/desktop", {"kind": "vnc", "machine": machine or here()})
    return str(answer["url"])


def terminal(machine: str | None = None) -> str:
    """A link to a web terminal on a machine."""
    answer = client().call("POST", "/pool/desktop", {"kind": "term", "machine": machine or here()})
    return str(answer["url"])


def quota() -> dict[str, Any]:
    """Limits of this account and what is left today."""
    return client().call("GET", "/pool/quota")
