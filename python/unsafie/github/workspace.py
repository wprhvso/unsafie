import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass

from unsafie.database import SessionLocal
from unsafie.database.models.repo import Repo, UserRepo
from unsafie.database.models.worktree import Worktree
from unsafie.database.repositories.github import (
    InstallationRepository,
    RepoRepository,
    UserRepoRepository,
    WorktreeRepository,
)
from unsafie.database.repositories.user import UserRepository
from unsafie.github.app.auth import installation_provider
from unsafie.github.client.repo import RepoClient
from unsafie.github.errors import GithubError, NotFound
from unsafie.github.vfs import Overlay, Tree

logger = logging.getLogger(__name__)

_locks: dict[tuple[int, str], asyncio.Lock] = defaultdict(asyncio.Lock)


@dataclass
class Session:
    repo: Repo
    binding: UserRepo
    client: RepoClient
    branch: str
    worktree: Worktree | None
    overlay: Overlay
    tree: Tree | None = None

    @property
    def dirty(self) -> bool:
        return len(self.overlay) > 0

    @property
    def label(self) -> str:
        return f"{self.repo.full}@{self.branch}"


def client_for(repo: Repo) -> RepoClient:
    return RepoClient(repo.owner, repo.name, installation_provider(repo.installation_id))


def lock_for(repo_id: int, branch: str) -> asyncio.Lock:
    return _locks[(repo_id, branch)]


async def resolve(user_id: int, ref: str | None) -> tuple[UserRepo, Repo]:
    async with SessionLocal() as session:
        repos = UserRepoRepository(session)
        if ref:
            found = await repos.resolve(user_id, ref)
            if found is None:
                known = [b.alias for b, _ in await repos.for_user(user_id)]
                hint = ", ".join(known) if known else "none yet — connect an account with /gh"
                raise NotFound(f"no repository '{ref}'. Available: {hint}")
            return found
        bound = await repos.for_user(user_id)
        if not bound:
            raise NotFound(
                "no repositories connected. The user must run /gh and install the app on their repositories."
            )
        if len(bound) > 1:
            names = ", ".join(b.alias for b, _ in bound)
            raise GithubError(f"specify the repository: {names}")
        return bound[0]


async def default_branch(repo: Repo, client: RepoClient) -> str:
    if repo.default_branch:
        return repo.default_branch
    info = await client.info()
    return info.get("default_branch") or "main"


async def open_session(user_id: int, ref: str | None, branch: str | None) -> Session:
    binding, repo = await resolve(user_id, ref)
    client = client_for(repo)
    name = branch or await default_branch(repo, client)
    async with SessionLocal() as session:
        worktree = await WorktreeRepository(session).get(repo.id, name)
    overlay = Overlay(worktree.changes if worktree else {})
    return Session(repo, binding, client, name, worktree, overlay)


async def ensure_worktree(state: Session) -> Worktree:
    if state.worktree is not None:
        return state.worktree
    sha = await state.client.ref_sha(state.branch)
    if sha is None:
        raise NotFound(f"branch '{state.branch}' does not exist in {state.repo.full}")
    commit = await state.client.commit(sha)
    async with SessionLocal() as session:
        state.worktree = await WorktreeRepository(session).create(
            state.repo.id, state.branch, sha, commit["tree"]["sha"]
        )
    logger.info("worktree opened %s at %s", state.label, sha[:7])
    return state.worktree


async def load_tree(state: Session) -> Tree:
    if state.tree is not None:
        return state.tree
    worktree = await ensure_worktree(state)
    data = await state.client.tree(worktree.base_tree_sha)
    if data.get("truncated"):
        logger.warning("%s tree is truncated by github", state.label)
    state.tree = Tree(data.get("tree", []), state.overlay)
    return state.tree


async def read(state: Session, path: str) -> bytes | None:
    entry = state.overlay.entry(path)
    if entry is not None:
        return None if entry.deleted else entry.data
    tree = await load_tree(state)
    sha = tree.blob_sha(path)
    if sha is None:
        return None
    return await state.client.blob(sha)


async def save(state: Session) -> None:
    worktree = await ensure_worktree(state)
    async with SessionLocal() as session:
        await WorktreeRepository(session).save(worktree.id, changes=state.overlay.to_json())


async def author_for(user_id: int, repo: Repo) -> dict | None:
    async with SessionLocal() as session:
        user = await UserRepository(session).get(user_id)
        installation = await InstallationRepository(session).get(repo.installation_id)
    if user and user.git_name and user.git_email:
        return {"name": user.git_name, "email": user.git_email}
    if installation and installation.account_login:
        login = installation.account_login
        return {"name": login, "email": f"{login}@users.noreply.github.com"}
    return None


async def repos_of(user_id: int) -> list[tuple[UserRepo, Repo]]:
    async with SessionLocal() as session:
        return await UserRepoRepository(session).for_user(user_id)


async def repo_by_full_name(owner: str, name: str) -> Repo | None:
    async with SessionLocal() as session:
        return await RepoRepository(session).by_full_name(owner, name)
