from typing import Any

from unsafie.github.client.base import GithubHTTP, TokenProvider


class UserClient(GithubHTTP):
    def __init__(self, token: TokenProvider | str, login: str | None = None) -> None:
        super().__init__(token)
        self.login = login

    async def me(self) -> dict:
        return await self.request("GET", "/user")

    async def search_issues(
        self, query: str, sort: str | None = None, limit: int = 30
    ) -> list[dict]:
        params: dict[str, Any] = {"q": query}
        if sort:
            params["sort"] = sort
        return await self.paginate("/search/issues", params, key="items").all(limit)

    async def search_code(self, query: str, limit: int = 30) -> list[dict]:
        return await self.paginate("/search/code", {"q": query}, key="items").all(limit)

    async def search_repos(self, query: str, limit: int = 20) -> list[dict]:
        return await self.paginate("/search/repositories", {"q": query}, key="items").all(limit)

    async def notifications(self, all_: bool = False, limit: int = 30) -> list[dict]:
        return await self.paginate("/notifications", {"all": str(all_).lower()}).all(limit)

    async def mark_notification(self, thread_id: str) -> None:
        await self.request("PATCH", f"/notifications/threads/{thread_id}")

    async def gists(self, limit: int = 30) -> list[dict]:
        return await self.paginate("/gists").all(limit)

    async def gist(self, gist_id: str) -> dict:
        return await self.request("GET", f"/gists/{gist_id}")

    async def create_gist(self, files: dict, description: str, public: bool) -> dict:
        return await self.request(
            "POST",
            "/gists",
            json_body={"files": files, "description": description, "public": public},
        )

    async def update_gist(self, gist_id: str, files: dict, description: str | None) -> dict:
        body: dict[str, Any] = {"files": files}
        if description is not None:
            body["description"] = description
        return await self.request("PATCH", f"/gists/{gist_id}", json_body=body)

    async def delete_gist(self, gist_id: str) -> None:
        await self.request("DELETE", f"/gists/{gist_id}")

    async def create_repo(self, name: str, org: str | None, **fields) -> dict:
        path = f"/orgs/{org}/repos" if org else "/user/repos"
        body = {"name": name, **{k: v for k, v in fields.items() if v is not None}}
        return await self.request("POST", path, json_body=body)

    async def installations(self) -> list[dict]:
        data = await self.request("GET", "/user/installations", params={"per_page": 100})
        return data.get("installations", [])
