OK = 0
FAILED = 1
USAGE = 2
NO_AUTH = 3
NOT_FOUND = 4
LIMIT = 5
UNAVAILABLE = 69


class CliError(Exception):
    def __init__(self, message: str, code: int = FAILED, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


class Usage(CliError):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message, USAGE, hint)


class NoAuth(CliError):
    def __init__(
        self,
        message: str = "no token",
        hint: str = "get one in Telegram with /auth, then: unsafie auth login --token …",
    ) -> None:
        super().__init__(message, NO_AUTH, hint)


class NotReady(CliError):
    def __init__(self, name: str, phase: int) -> None:
        super().__init__(
            f"`unsafie {name}` is declared but not implemented yet (phase {phase})",
            UNAVAILABLE,
            "see `unsafie help --json` for what already works",
        )
        self.phase = phase
