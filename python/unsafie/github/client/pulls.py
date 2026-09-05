from typing import Any


class PullsMixin:
    async def pulls(self, state: str = "open", limit: int = 30) -> list[dict]:
        return await self.paginate(
            f"{self.base}/pulls", {"state": state, "sort": "updated", "direction": "desc"}
        ).all(limit)

    async def pull(self, number: int) -> dict:
        return await self.request("GET", f"{self.base}/pulls/{number}")

    async def create_pull(
        self, title: str, head: str, base: str, body: str | None, draft: bool = False
    ) -> dict:
        return await self.request(
            "POST",
            f"{self.base}/pulls",
            json_body={
                "title": title,
                "head": head,
                "base": base,
                "body": body or "",
                "draft": draft,
            },
        )

    async def update_pull(self, number: int, **fields) -> dict:
        payload = {k: v for k, v in fields.items() if v is not None}
        return await self.request("PATCH", f"{self.base}/pulls/{number}", json_body=payload)

    async def merge_pull(
        self,
        number: int,
        method: str = "merge",
        title: str | None = None,
        message: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"merge_method": method}
        if title:
            payload["commit_title"] = title
        if message:
            payload["commit_message"] = message
        return await self.request("PUT", f"{self.base}/pulls/{number}/merge", json_body=payload)

    async def pull_files(self, number: int, limit: int = 300) -> list[dict]:
        return await self.paginate(f"{self.base}/pulls/{number}/files").all(limit)

    async def pull_commits(self, number: int, limit: int = 100) -> list[dict]:
        return await self.paginate(f"{self.base}/pulls/{number}/commits").all(limit)

    async def pull_diff(self, number: int) -> str:
        data = await self.request(
            "GET", f"{self.base}/pulls/{number}", accept="application/vnd.github.diff", raw=True
        )
        return data.decode(errors="replace") if isinstance(data, bytes) else str(data)

    async def reviews(self, number: int) -> list[dict]:
        return await self.paginate(f"{self.base}/pulls/{number}/reviews").all(50)

    async def review(
        self, number: int, event: str, body: str | None, comments: list[dict] | None
    ) -> dict:
        payload: dict[str, Any] = {"event": event}
        if body:
            payload["body"] = body
        if comments:
            payload["comments"] = comments
        return await self.request("POST", f"{self.base}/pulls/{number}/reviews", json_body=payload)

    async def request_reviewers(self, number: int, reviewers: list[str]) -> dict:
        return await self.request(
            "POST",
            f"{self.base}/pulls/{number}/requested_reviewers",
            json_body={"reviewers": reviewers},
        )

    async def review_comments(self, number: int, limit: int = 100) -> list[dict]:
        return await self.paginate(f"{self.base}/pulls/{number}/comments").all(limit)
