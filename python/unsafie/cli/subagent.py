import os
import sys
from typing import Any

from unsafie.cli.client import client
from unsafie_wire import markers


def _turn() -> str | None:
    return os.environ.get("UNSAFIE_TURN") or None


def spawn(prompt: str, *, title: str | None = None, timeout: float = 600.0) -> dict[str, Any]:
    body = {
        "prompt": prompt,
        "title": title,
        "timeout": timeout,
        "parent_turn_id": _turn(),
    }
    return client().call("POST", "/subagents", body)


def wait(*ids: str, timeout: float = 600.0) -> list[dict[str, Any]]:
    body = {
        "ids": list(ids),
        "timeout": timeout,
    }
    return client().call("POST", "/subagents/wait", body, timeout=timeout + 30.0)


def status(turn_id: str) -> dict[str, Any]:
    return client().call("GET", f"/subagents/{turn_id}")


def listing(limit: int = 50) -> list[dict[str, Any]]:
    params = {"limit": limit, "parent_turn_id": _turn()}
    return client().call("GET", "/subagents", params=params)


def cancel(*ids: str) -> dict[str, Any]:
    return client().call("POST", "/subagents/cancel", {"ids": list(ids)})


def finish(result: str) -> dict[str, Any]:
    turn_id = _turn()
    if turn_id:
        client().call("POST", f"/subagents/{turn_id}/result", {"result": result})
    sys.stderr.write(markers.stop() + "\n")
    sys.stderr.flush()
    return {"finished": True, "result": result}
