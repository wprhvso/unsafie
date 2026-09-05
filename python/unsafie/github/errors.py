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
            f"no GitHub token{who}. Ask the user to run /gh <token> with a personal access token "
            "(classic: scope repo, plus workflow, gist, notifications, read:org)."
        )


class AppNotInstalled(GithubError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "the GitHub App is not set up yet; an administrator must create it in the admin "
            "panel. It is only needed for event notifications and checks — everything else "
            "works on the token."
        )
