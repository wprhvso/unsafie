"""Blob storage used inside the SDK: screenshots, browser profiles, file copies.

Not part of the agent's surface — the agent keeps what matters in git or on a server.
"""

from pathlib import Path

from unsafie_sdk.client import client


def put(key: str, data: bytes | str | Path) -> dict:
    """Store bytes, text or a file under a key."""
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
