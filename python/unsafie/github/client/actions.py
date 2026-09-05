from typing import Any


class ActionsMixin:
    async def workflows(self) -> list[dict]:
        data = await self.request("GET", f"{self.base}/actions/workflows", params={"per_page": 100})
        return data.get("workflows", [])

    async def runs(
        self,
        workflow: str | int | None = None,
        branch: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if branch:
            params["branch"] = branch
        if status:
            params["status"] = status
        path = (
            f"{self.base}/actions/workflows/{workflow}/runs"
            if workflow
            else f"{self.base}/actions/runs"
        )
        return await self.paginate(path, params, key="workflow_runs").all(limit)

    async def run(self, run_id: int) -> dict:
        return await self.request("GET", f"{self.base}/actions/runs/{run_id}")

    async def jobs(self, run_id: int) -> list[dict]:
        return await self.paginate(f"{self.base}/actions/runs/{run_id}/jobs", key="jobs").all(100)

    async def job_logs(self, job_id: int) -> bytes:
        data = await self.request(
            "GET", f"{self.base}/actions/jobs/{job_id}/logs", raw=True, allow_404=True
        )
        return data or b""

    async def dispatch(self, workflow: str, ref: str, inputs: dict | None) -> None:
        await self.request(
            "POST",
            f"{self.base}/actions/workflows/{workflow}/dispatches",
            json_body={"ref": ref, "inputs": inputs or {}},
        )

    async def rerun(self, run_id: int, failed_only: bool = False) -> None:
        suffix = "rerun-failed-jobs" if failed_only else "rerun"
        await self.request("POST", f"{self.base}/actions/runs/{run_id}/{suffix}")

    async def cancel(self, run_id: int) -> None:
        await self.request("POST", f"{self.base}/actions/runs/{run_id}/cancel")

    async def artifacts(self, run_id: int) -> list[dict]:
        data = await self.request("GET", f"{self.base}/actions/runs/{run_id}/artifacts")
        return data.get("artifacts", [])

    async def artifact_zip(self, artifact_id: int) -> bytes:
        return await self.request(
            "GET", f"{self.base}/actions/artifacts/{artifact_id}/zip", raw=True
        )
