import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.database.models.commit_log import CommitLog
from unsafie.database.models.github_account import GithubAccount
from unsafie.database.models.github_app import GithubApp
from unsafie.database.models.installation import Installation, InstallationAccount
from unsafie.database.models.repo import Repo, UserRepo
from unsafie.database.models.worktree import Worktree

logger = logging.getLogger(__name__)


class GithubAppRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self) -> GithubApp | None:
        return await self.session.get(GithubApp, 1)

    async def save(self, **fields) -> GithubApp:
        app = await self.get()
        if app is None:
            app = GithubApp(id=1, **fields)
            self.session.add(app)
        else:
            for k, v in fields.items():
                setattr(app, k, v)
        await self.session.commit()
        logger.info("github app saved slug=%s app_id=%s", app.slug, app.app_id)
        return app

    async def delete(self) -> bool:
        app = await self.get()
        if app is None:
            return False
        await self.session.delete(app)
        await self.session.commit()
        return True


class GithubAccountRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def for_user(self, user_id: int) -> list[GithubAccount]:
        return list(
            await self.session.scalars(
                select(GithubAccount)
                .where(GithubAccount.user_id == user_id)
                .order_by(GithubAccount.id)
            )
        )

    async def get(self, account_id: int) -> GithubAccount | None:
        return await self.session.get(GithubAccount, account_id)

    async def by_github_id(self, user_id: int, github_id: int) -> GithubAccount | None:
        return await self.session.scalar(
            select(GithubAccount).where(
                GithubAccount.user_id == user_id, GithubAccount.github_id == github_id
            )
        )

    async def by_login(self, user_id: int, login: str) -> GithubAccount | None:
        return await self.session.scalar(
            select(GithubAccount).where(
                GithubAccount.user_id == user_id, func.lower(GithubAccount.login) == login.lower()
            )
        )

    async def logins(self, user_id: int) -> set[str]:
        rows = await self.session.scalars(
            select(GithubAccount.login).where(GithubAccount.user_id == user_id)
        )
        return {r.lower() for r in rows}

    async def upsert(
        self,
        user_id: int,
        github_id: int,
        login: str,
        *,
        token: str,
        scopes: str | None = None,
    ) -> GithubAccount:
        row = await self.by_github_id(user_id, github_id)
        if row is None:
            row = GithubAccount(user_id=user_id, github_id=github_id, login=login)
            self.session.add(row)
        row.login = login
        row.token = token
        row.scopes = scopes
        row.last_used_at = datetime.now(UTC)
        await self.session.commit()
        logger.info("user=%s github account %s linked", user_id, login)
        return row

    async def touch(self, account_id: int) -> None:
        row = await self.get(account_id)
        if row is None:
            return
        row.last_used_at = datetime.now(UTC)
        await self.session.commit()

    async def remove(self, user_id: int, account_id: int) -> GithubAccount | None:
        row = await self.get(account_id)
        if row is None or row.user_id != user_id:
            return None
        await self.session.delete(row)
        await self.session.commit()
        return row

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[GithubAccount], int]:
        total = await self.session.scalar(select(func.count()).select_from(GithubAccount)) or 0
        rows = await self.session.scalars(
            select(GithubAccount).order_by(GithubAccount.id).offset(offset).limit(limit)
        )
        return list(rows), int(total)


class InstallationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, installation_id: int) -> Installation | None:
        return await self.session.get(Installation, installation_id)

    async def all(self, include_suspended: bool = True) -> list[Installation]:
        stmt = select(Installation).order_by(Installation.id)
        if not include_suspended:
            stmt = stmt.where(Installation.suspended.is_(False))
        return list(await self.session.scalars(stmt))

    async def upsert(
        self,
        installation_id: int,
        *,
        account_id: int,
        account_login: str,
        account_type: str,
        repository_selection: str,
    ) -> Installation:
        row = await self.get(installation_id)
        if row is None:
            row = Installation(
                id=installation_id,
                account_id=account_id,
                account_login=account_login,
                account_type=account_type,
                repository_selection=repository_selection,
            )
            self.session.add(row)
        else:
            row.account_id = account_id
            row.account_login = account_login
            row.account_type = account_type
            row.repository_selection = repository_selection
            row.suspended = False
        await self.session.commit()
        logger.info("installation=%s %s (%s) saved", installation_id, account_login, account_type)
        return row

    async def set_suspended(self, installation_id: int, suspended: bool) -> None:
        row = await self.get(installation_id)
        if row is None:
            return
        row.suspended = suspended
        await self.session.commit()

    async def link_account(self, installation_id: int, github_account_id: int) -> None:
        exists = await self.session.get(InstallationAccount, (installation_id, github_account_id))
        if exists is None:
            self.session.add(
                InstallationAccount(
                    installation_id=installation_id, github_account_id=github_account_id
                )
            )
            await self.session.commit()

    async def for_account(self, github_account_id: int) -> list[Installation]:
        rows = await self.session.scalars(
            select(Installation)
            .join(InstallationAccount, InstallationAccount.installation_id == Installation.id)
            .where(InstallationAccount.github_account_id == github_account_id)
            .order_by(Installation.id)
        )
        return list(rows)

    async def for_user(self, user_id: int) -> list[Installation]:
        rows = await self.session.scalars(
            select(Installation)
            .join(InstallationAccount, InstallationAccount.installation_id == Installation.id)
            .join(GithubAccount, GithubAccount.id == InstallationAccount.github_account_id)
            .where(GithubAccount.user_id == user_id)
            .order_by(Installation.id)
            .distinct()
        )
        return list(rows)

    async def delete(self, installation_id: int) -> bool:
        row = await self.get(installation_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True


class RepoRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, repo_id: int) -> Repo | None:
        return await self.session.get(Repo, repo_id)

    async def by_github_id(self, github_id: int) -> Repo | None:
        return await self.session.scalar(select(Repo).where(Repo.github_id == github_id))

    async def by_full_name(self, owner: str, name: str) -> Repo | None:
        return await self.session.scalar(
            select(Repo).where(
                func.lower(Repo.owner) == owner.lower(), func.lower(Repo.name) == name.lower()
            )
        )

    async def for_installation(self, installation_id: int) -> list[Repo]:
        return list(
            await self.session.scalars(
                select(Repo)
                .where(Repo.installation_id == installation_id)
                .order_by(Repo.owner, Repo.name)
            )
        )

    async def upsert(
        self,
        installation_id: int | None,
        github_id: int,
        owner: str,
        name: str,
        default_branch: str,
        private: bool,
    ) -> Repo:
        """installation_id=None means the repository is known from a token, not from an installation."""
        row = await self.by_github_id(github_id)
        if row is None:
            row = Repo(
                installation_id=installation_id,
                github_id=github_id,
                owner=owner,
                name=name,
                default_branch=default_branch,
                private=private,
            )
            self.session.add(row)
        else:
            if installation_id is not None:
                row.installation_id = installation_id
            row.owner = owner
            row.name = name
            row.default_branch = default_branch
            row.private = private
        await self.session.commit()
        return row

    async def delete_by_github_id(self, github_id: int) -> bool:
        row = await self.by_github_id(github_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[Repo], int]:
        total = await self.session.scalar(select(func.count()).select_from(Repo)) or 0
        rows = await self.session.scalars(
            select(Repo).order_by(Repo.owner, Repo.name).offset(offset).limit(limit)
        )
        return list(rows), int(total)


class UserRepoRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def for_user(self, user_id: int) -> list[tuple[UserRepo, Repo]]:
        rows = await self.session.execute(
            select(UserRepo, Repo)
            .join(Repo, Repo.id == UserRepo.repo_id)
            .where(UserRepo.user_id == user_id)
            .order_by(UserRepo.alias)
        )
        return [(u, r) for u, r in rows]

    async def resolve(self, user_id: int, ref: str) -> tuple[UserRepo, Repo] | None:
        ref = ref.strip()
        cond = func.lower(UserRepo.alias) == ref.lower()
        if "/" in ref:
            owner, _, name = ref.partition("/")
            cond = cond | (
                (func.lower(Repo.owner) == owner.lower()) & (func.lower(Repo.name) == name.lower())
            )
        row = (
            await self.session.execute(
                select(UserRepo, Repo)
                .join(Repo, Repo.id == UserRepo.repo_id)
                .where(UserRepo.user_id == user_id, cond)
                .limit(1)
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def bind(self, user_id: int, repo: Repo, alias: str | None = None) -> UserRepo:
        existing = await self.session.scalar(
            select(UserRepo).where(UserRepo.user_id == user_id, UserRepo.repo_id == repo.id)
        )
        if existing is not None:
            return existing
        taken = {
            a.lower()
            for a in await self.session.scalars(
                select(UserRepo.alias).where(UserRepo.user_id == user_id)
            )
        }
        candidates = [alias] if alias else [repo.name, f"{repo.owner}-{repo.name}"]
        chosen = next((c for c in candidates if c.lower() not in taken), None)
        if chosen is None:
            base = f"{repo.owner}-{repo.name}"
            n = 2
            while f"{base}-{n}".lower() in taken:
                n += 1
            chosen = f"{base}-{n}"
        row = UserRepo(user_id=user_id, repo_id=repo.id, alias=chosen)
        self.session.add(row)
        await self.session.commit()
        logger.info("user=%s repo=%s bound as %s", user_id, repo.full, chosen)
        return row

    async def rename(self, user_id: int, ref: str, alias: str) -> UserRepo | None:
        found = await self.resolve(user_id, ref)
        if found is None:
            return None
        found[0].alias = alias
        await self.session.commit()
        return found[0]

    async def unbind(self, user_id: int, ref: str) -> UserRepo | None:
        found = await self.resolve(user_id, ref)
        if found is None:
            return None
        await self.session.delete(found[0])
        await self.session.commit()
        return found[0]

    async def users_for_repo(self, repo_id: int) -> list[UserRepo]:
        return list(await self.session.scalars(select(UserRepo).where(UserRepo.repo_id == repo_id)))


class WorktreeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, repo_id: int, branch: str) -> Worktree | None:
        return await self.session.scalar(
            select(Worktree).where(Worktree.repo_id == repo_id, Worktree.branch == branch)
        )

    async def for_repo(self, repo_id: int) -> list[Worktree]:
        return list(
            await self.session.scalars(
                select(Worktree).where(Worktree.repo_id == repo_id).order_by(Worktree.branch)
            )
        )

    async def for_user(self, user_id: int) -> list[tuple[UserRepo, Repo, Worktree]]:
        rows = await self.session.execute(
            select(UserRepo, Repo, Worktree)
            .join(Repo, Repo.id == UserRepo.repo_id)
            .join(Worktree, Worktree.repo_id == Repo.id)
            .where(UserRepo.user_id == user_id)
            .order_by(UserRepo.alias, Worktree.branch)
        )
        return [(u, r, w) for u, r, w in rows]

    async def create(self, repo_id: int, branch: str, commit: str, tree: str) -> Worktree:
        wt = Worktree(
            repo_id=repo_id, branch=branch, base_commit_sha=commit, base_tree_sha=tree, changes={}
        )
        self.session.add(wt)
        await self.session.commit()
        logger.info("worktree created repo_id=%s branch=%s sha=%s", repo_id, branch, commit[:7])
        return wt

    async def save(self, worktree_id: int, **fields) -> None:
        wt = await self.session.get(Worktree, worktree_id)
        if wt is None:
            return
        for k, v in fields.items():
            setattr(wt, k, v)
        await self.session.commit()

    async def delete(self, repo_id: int, branch: str) -> None:
        await self.session.execute(
            delete(Worktree).where(Worktree.repo_id == repo_id, Worktree.branch == branch)
        )
        await self.session.commit()

    async def page(
        self, offset: int = 0, limit: int = 50
    ) -> tuple[list[tuple[Worktree, Repo]], int]:
        total = await self.session.scalar(select(func.count()).select_from(Worktree)) or 0
        rows = await self.session.execute(
            select(Worktree, Repo)
            .join(Repo, Repo.id == Worktree.repo_id)
            .order_by(Worktree.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(w, r) for w, r in rows], int(total)

    async def log(
        self,
        worktree_id: int,
        user_id: int | None,
        kind: str,
        sha: str,
        previous: str | None,
        message: str,
    ) -> None:
        self.session.add(
            CommitLog(
                worktree_id=worktree_id,
                user_id=user_id,
                kind=kind,
                sha=sha,
                previous_sha=previous,
                message=message[:2000],
            )
        )
        await self.session.commit()

    async def logs(self, worktree_id: int, n: int = 20) -> list[CommitLog]:
        return list(
            await self.session.scalars(
                select(CommitLog)
                .where(CommitLog.worktree_id == worktree_id)
                .order_by(CommitLog.id.desc())
                .limit(n)
            )
        )

    async def known_sha(self, worktree_id: int, sha: str) -> bool:
        row = await self.session.scalar(
            select(CommitLog.id).where(
                CommitLog.worktree_id == worktree_id,
                (CommitLog.sha == sha) | (CommitLog.previous_sha == sha),
            )
        )
        return row is not None
