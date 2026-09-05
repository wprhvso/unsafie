from unsafie.errors import OpsError


class GithubError(OpsError):
    pass


class NotFound(GithubError):
    pass


class Conflict(GithubError):
    pass


class UserAuthRequired(GithubError):
    def __init__(self, login: str | None = None) -> None:
        who = f" for account {login}" if login else ""
        super().__init__(
            f"GitHub authorization has expired{who}. Ask the user to run /gh and connect the account again. "
            "Repository tools keep working; search, gists and notifications do not."
        )


class AppNotInstalled(GithubError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "the GitHub App is not set up yet; an administrator must create it in the admin panel"
        )
