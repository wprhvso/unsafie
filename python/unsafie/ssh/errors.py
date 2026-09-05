from unsafie.errors import OpsError


class SshError(OpsError):
    pass


class HostKeyChanged(SshError):
    def __init__(self, alias: str, expected: str, got: str) -> None:
        super().__init__(
            f"the host key of {alias} has changed: expected {expected}, got {got}. "
            "This is either a reinstall or a man-in-the-middle. Do not connect; ask the user to "
            "confirm and re-add the host with /ssh."
        )


class NoKey(SshError):
    def __init__(self) -> None:
        super().__init__(
            "the user has no SSH key yet. Ask them to run /ssh key — it will generate one and show "
            "the public part to put into authorized_keys on the server."
        )
