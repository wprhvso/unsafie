from typing import Any


class ReleasesMixin:
    async def releases(self, limit: int = 20) -> list[dict]:
        return await self.paginate(f"{self.base}/releases").all(limit)

    async def latest_release(self) -> dict | None:
        return await self.request("GET", f"{self.base}/releases/latest", allow_404=True)

    async def release(self, tag: str) -> dict | None:
        return await self.request("GET", f"{self.base}/releases/tags/{tag}", allow_404=True)

    async def create_release(
        self,
        tag: str,
        name: str | None,
        body: str | None,
        target: str | None,
        draft: bool,
        prerelease: bool,
    ) -> dict:
        payload: dict[str, Any] = {
            "tag_name": tag,
            "name": name or tag,
            "body": body or "",
            "draft": draft,
            "prerelease": prerelease,
        }
        if target:
            payload["target_commitish"] = target
        return await self.request("POST", f"{self.base}/releases", json_body=payload)

    async def update_release(self, release_id: int, **fields) -> dict:
        payload = {k: v for k, v in fields.items() if v is not None}
        return await self.request("PATCH", f"{self.base}/releases/{release_id}", json_body=payload)

    async def delete_release(self, release_id: int) -> None:
        await self.request("DELETE", f"{self.base}/releases/{release_id}")
