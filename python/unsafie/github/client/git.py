import base64
import json
from collections.abc import Iterable
from typing import Any

from unsafie.github import cache
from unsafie.github.client.base import RAW, run_limited


def _envelope(body: bytes) -> bytes:
    """The API answered with the JSON wrapper instead of the raw blob — unwrap it."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if not isinstance(data, dict):
        return body
    if data.get("encoding") == "base64":
        return base64.b64decode(data.get("content") or "")
    return (data.get("content") or "").encode()


class GitMixin:
    async def branch(self, name: str) -> dict | None:
        return await self.request("GET", f"{self.base}/branches/{name}", allow_404=True)

    async def ref_sha(self, ref: str) -> str | None:
        data = await self.request("GET", f"{self.base}/git/ref/heads/{ref}", allow_404=True)
        return data["object"]["sha"] if data else None

    async def commit(self, sha: str) -> dict:
        return await self.request("GET", f"{self.base}/git/commits/{sha}")

    async def commits(
        self, ref: str | None = None, path: str | None = None, limit: int = 20
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if ref:
            params["sha"] = ref
        if path:
            params["path"] = path
        return await self.paginate(f"{self.base}/commits", params).all(limit)

    async def compare(self, base: str, head: str) -> dict:
        return await self.request("GET", f"{self.base}/compare/{base}...{head}")

    async def tree(self, sha: str, recursive: bool = True) -> dict:
        key = sha if recursive else f"{sha}.flat"
        cached = await cache.trees.get_json(key)
        if cached is not None:
            return cached
        params = {"recursive": "1"} if recursive else None
        data = await self.request("GET", f"{self.base}/git/trees/{sha}", params=params)
        if isinstance(data, dict) and not data.get("truncated"):
            await cache.trees.put_json(key, data)
        return data

    async def blob(self, sha: str) -> bytes:
        """A blob by its sha. The sha is the content hash, so the cache never goes stale."""
        cached = await cache.blobs.get(sha)
        if cached is not None:
            return cached
        body = await self.request("GET", f"{self.base}/git/blobs/{sha}", accept=RAW, raw=True)
        data = body if isinstance(body, bytes) else b""
        if data[:1] == b"{" and cache.git_sha(data) != sha:
            data = _envelope(data)
        await cache.blobs.put(sha, data)
        return data

    async def blobs(self, shas: Iterable[str]) -> dict[str, bytes]:
        """Many blobs at once: deduplicated and fetched in parallel instead of one by one."""
        unique = list(dict.fromkeys(sha for sha in shas if sha))
        if not unique:
            return {}
        results = await run_limited([self.blob(sha) for sha in unique])
        return dict(zip(unique, results, strict=True))

    async def create_blob(self, data: bytes) -> str:
        result = await self.request(
            "POST",
            f"{self.base}/git/blobs",
            json_body={"content": base64.b64encode(data).decode(), "encoding": "base64"},
        )
        return result["sha"]

    async def create_tree(self, entries: list[dict], base_tree: str | None = None) -> str:
        body: dict[str, Any] = {"tree": entries}
        if base_tree:
            body["base_tree"] = base_tree
        result = await self.request("POST", f"{self.base}/git/trees", json_body=body)
        return result["sha"]

    async def create_commit(
        self, message: str, tree: str, parents: list[str], author: dict | None = None
    ) -> dict:
        body: dict[str, Any] = {"message": message, "tree": tree, "parents": parents}
        if author:
            body["author"] = author
            body["committer"] = author
        return await self.request("POST", f"{self.base}/git/commits", json_body=body)

    async def update_ref(self, ref: str, sha: str, force: bool = False) -> dict:
        return await self.request(
            "PATCH", f"{self.base}/git/refs/heads/{ref}", json_body={"sha": sha, "force": force}
        )

    async def create_ref(self, ref: str, sha: str) -> dict:
        return await self.request(
            "POST", f"{self.base}/git/refs", json_body={"ref": f"refs/heads/{ref}", "sha": sha}
        )

    async def delete_ref(self, ref: str) -> None:
        await self.request("DELETE", f"{self.base}/git/refs/heads/{ref}")

    async def branches(self, limit: int = 100) -> list[dict]:
        return await self.paginate(f"{self.base}/branches").all(limit)

    async def tags(self, limit: int = 50) -> list[dict]:
        return await self.paginate(f"{self.base}/tags").all(limit)

    async def contents(self, path: str, ref: str | None = None) -> Any:
        params = {"ref": ref} if ref else None
        return await self.request(
            "GET", f"{self.base}/contents/{path}", params=params, allow_404=True
        )
