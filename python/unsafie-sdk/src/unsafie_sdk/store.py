import json
from pathlib import Path
from typing import Any

from unsafie_sdk.client import client
from unsafie_sdk.errors import NotFound


def put(key: str, data: bytes | str | Path) -> dict:
    """Store bytes, text or a file under a key. Survives the machine."""
    if isinstance(data, Path):
        payload = data.read_bytes()
    elif isinstance(data, str):
        payload = data.encode()
    else:
        payload = data
    return client().upload(f"/blobs/{key}", payload)


def get(key: str) -> bytes:
    """Read a stored blob."""
    return client().call("GET", f"/blobs/{key}", raw=True)


def text(key: str, encoding: str = "utf-8") -> str:
    """Read a stored blob as text."""
    return get(key).decode(encoding, errors="replace")


def download(key: str, path: str | Path) -> Path:
    """Write a stored blob to a file."""
    target = Path(path)
    target.write_bytes(get(key))
    return target


def listing(prefix: str = "", limit: int = 50) -> list[dict]:
    """Stored keys with their size and time."""
    answer = client().call("GET", "/blobs", params={"prefix": prefix, "limit": limit})
    return answer.get("blobs", [])


def delete(key: str) -> dict:
    """Forget a stored blob."""
    return client().call("DELETE", f"/blobs/{key}")


class Kv:
    """Small values that outlive the machine: kv['plan'] = 'step 2'."""

    def get(self, key: str, default: Any = None) -> Any:
        try:
            found = client().call("GET", f"/kv/{key}")
        except NotFound:
            return default
        raw = (found or {}).get("value")
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    def set(self, key: str, value: Any) -> Any:
        body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        client().call("PUT", f"/kv/{key}", {"value": body})
        return value

    def keys(self, prefix: str = "") -> list[str]:
        answer = client().call("GET", "/kv", params={"prefix": prefix})
        return sorted((answer or {}).get("values", {}))

    def delete(self, key: str) -> dict:
        return client().call("DELETE", f"/kv/{key}")

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: str) -> None:
        self.delete(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key, None) is not None


class Secrets:
    """API keys of this account. Reading one never puts it in the chat history."""

    def get(self, name: str) -> str:
        return str(client().call("GET", f"/secrets/{name}")["value"])

    def set(self, name: str, value: str) -> dict:
        return client().call("PUT", f"/secrets/{name}", {"value": value})

    def names(self) -> list[str]:
        return [row["name"] for row in client().call("GET", "/secrets").get("secrets", [])]

    def delete(self, name: str) -> dict:
        return client().call("DELETE", f"/secrets/{name}")

    def environ(self, *names: str) -> dict[str, str]:
        """Put secrets into os.environ and return them."""
        import os

        if names:
            out = {name: self.get(name) for name in names}
        else:
            answer = client().call("GET", "/secrets/values")
            out = dict((answer or {}).get("values", {}))
        os.environ.update(out)
        return out

    def __getitem__(self, name: str) -> str:
        return self.get(name)

    def __setitem__(self, name: str, value: str) -> None:
        self.set(name, value)


kv = Kv()
secrets = Secrets()
