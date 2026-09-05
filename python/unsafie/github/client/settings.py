from typing import Any


class SettingsMixin:
    async def info(self) -> dict:
        return await self.request("GET", self.base)

    async def update(self, **fields) -> dict:
        payload = {k: v for k, v in fields.items() if v is not None}
        return await self.request("PATCH", self.base, json_body=payload)

    async def topics(self) -> list[str]:
        data = await self.request("GET", f"{self.base}/topics")
        return data.get("names", [])

    async def set_topics(self, names: list[str]) -> list[str]:
        data = await self.request("PUT", f"{self.base}/topics", json_body={"names": names})
        return data.get("names", [])

    async def collaborators(self) -> list[dict]:
        return await self.paginate(f"{self.base}/collaborators").all(100)

    async def branch_protection(self, branch: str) -> dict | None:
        return await self.request(
            "GET", f"{self.base}/branches/{branch}/protection", allow_404=True
        )

    async def protect_branch(self, branch: str, body: dict) -> dict:
        return await self.request(
            "PUT", f"{self.base}/branches/{branch}/protection", json_body=body
        )

    async def unprotect_branch(self, branch: str) -> None:
        await self.request("DELETE", f"{self.base}/branches/{branch}/protection")

    async def public_key(self, scope: str = "actions") -> dict:
        return await self.request("GET", f"{self.base}/{scope}/secrets/public-key")

    async def secrets(self, scope: str = "actions") -> list[dict]:
        data = await self.request("GET", f"{self.base}/{scope}/secrets", params={"per_page": 100})
        return data.get("secrets", [])

    async def put_secret(
        self, name: str, encrypted: str, key_id: str, scope: str = "actions"
    ) -> None:
        await self.request(
            "PUT",
            f"{self.base}/{scope}/secrets/{name}",
            json_body={"encrypted_value": encrypted, "key_id": key_id},
        )

    async def delete_secret(self, name: str, scope: str = "actions") -> None:
        await self.request("DELETE", f"{self.base}/{scope}/secrets/{name}")

    async def variables(self) -> list[dict]:
        data = await self.request("GET", f"{self.base}/actions/variables", params={"per_page": 100})
        return data.get("variables", [])

    async def put_variable(self, name: str, value: str) -> None:
        existing = await self.request(
            "GET", f"{self.base}/actions/variables/{name}", allow_404=True
        )
        body: dict[str, Any] = {"name": name, "value": value}
        if existing:
            await self.request("PATCH", f"{self.base}/actions/variables/{name}", json_body=body)
        else:
            await self.request("POST", f"{self.base}/actions/variables", json_body=body)

    async def delete_variable(self, name: str) -> None:
        await self.request("DELETE", f"{self.base}/actions/variables/{name}")
