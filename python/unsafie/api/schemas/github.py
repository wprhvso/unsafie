from pydantic import BaseModel, ConfigDict


class RepoAdd(BaseModel):
    repo: str
    alias: str | None = None


class RepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alias: str
    owner: str
    name: str
    default_branch: str


class GithubToken(BaseModel):
    token: str


class GithubRead(BaseModel):
    login: str | None


class GitAuthor(BaseModel):
    name: str
    email: str


class WorktreeRead(BaseModel):
    repo: str
    branch: str
    base_commit_sha: str
    changes: int
    pending: str | None
    stash: bool
