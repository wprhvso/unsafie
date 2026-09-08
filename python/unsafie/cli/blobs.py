from pathlib import Path

from unsafie.cli.client import client


def put(key: str, data: bytes | str | Path) -> dict:
    if isinstance(data, Path):
        payload = data.read_bytes()
    elif isinstance(data, str):
        payload = data.encode()
    else:
        payload = data
    return client().upload(f"/blobs/{key}", payload)


def get(key: str) -> bytes:
    return client().call("GET", f"/blobs/{key}", raw=True)


def listing(prefix: str = "", limit: int = 50) -> list[dict]:
    answer = client().call("GET", "/blobs", params={"prefix": prefix, "limit": limit})
    return answer.get("blobs", [])


def delete(key: str) -> dict:
    return client().call("DELETE", f"/blobs/{key}")
