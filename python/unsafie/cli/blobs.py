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
