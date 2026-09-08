class UnsafieError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message if not hint else f"{message}\n{hint}")
        self.message = message
        self.hint = hint


class NotAuthorized(UnsafieError):
    pass


class NotFound(UnsafieError):
    pass


class LimitReached(UnsafieError):
    pass


class Refused(UnsafieError):
    pass
