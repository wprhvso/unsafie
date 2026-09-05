from typing import Any


class IssuesMixin:
    async def issues(
        self, state: str = "open", labels: str | None = None, limit: int = 30
    ) -> list[dict]:
        params: dict[str, Any] = {"state": state, "sort": "updated"}
        if labels:
            params["labels"] = labels
        items = await self.paginate(f"{self.base}/issues", params).all(limit + 20)
        return [i for i in items if "pull_request" not in i][:limit]

    async def issue(self, number: int) -> dict:
        return await self.request("GET", f"{self.base}/issues/{number}")

    async def create_issue(
        self, title: str, body: str | None, labels: list[str] | None, assignees: list[str] | None
    ) -> dict:
        payload: dict[str, Any] = {"title": title, "body": body or ""}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return await self.request("POST", f"{self.base}/issues", json_body=payload)

    async def update_issue(self, number: int, **fields) -> dict:
        payload = {k: v for k, v in fields.items() if v is not None}
        return await self.request("PATCH", f"{self.base}/issues/{number}", json_body=payload)

    async def comments(self, number: int, limit: int = 50) -> list[dict]:
        return await self.paginate(f"{self.base}/issues/{number}/comments").all(limit)

    async def comment(self, number: int, body: str) -> dict:
        return await self.request(
            "POST", f"{self.base}/issues/{number}/comments", json_body={"body": body}
        )

    async def update_comment(self, comment_id: int, body: str) -> dict:
        return await self.request(
            "PATCH", f"{self.base}/issues/comments/{comment_id}", json_body={"body": body}
        )

    async def delete_comment(self, comment_id: int) -> None:
        await self.request("DELETE", f"{self.base}/issues/comments/{comment_id}")

    async def labels(self) -> list[dict]:
        return await self.paginate(f"{self.base}/labels").all(100)

    async def add_labels(self, number: int, labels: list[str]) -> list[dict]:
        return await self.request(
            "POST", f"{self.base}/issues/{number}/labels", json_body={"labels": labels}
        )

    async def remove_label(self, number: int, label: str) -> None:
        await self.request("DELETE", f"{self.base}/issues/{number}/labels/{label}")

    async def milestones(self) -> list[dict]:
        return await self.paginate(f"{self.base}/milestones").all(50)
