from unsafie.github.client.actions import ActionsMixin
from unsafie.github.client.base import GithubHTTP, TokenProvider
from unsafie.github.client.git import GitMixin
from unsafie.github.client.issues import IssuesMixin
from unsafie.github.client.pulls import PullsMixin
from unsafie.github.client.releases import ReleasesMixin
from unsafie.github.client.settings import SettingsMixin


class RepoClient(
    GithubHTTP, GitMixin, IssuesMixin, PullsMixin, ActionsMixin, ReleasesMixin, SettingsMixin
):
    def __init__(self, owner: str, name: str, token: TokenProvider | str) -> None:
        super().__init__(token)
        self.owner = owner
        self.name = name

    @property
    def full(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def base(self) -> str:
        return f"/repos/{self.owner}/{self.name}"
