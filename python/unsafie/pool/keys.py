from unsafie import cluster

NAMESPACE = "pool"


def machine(name: str) -> str:
    return cluster.key(NAMESPACE, "m", name)


def idle() -> str:
    return cluster.key(NAMESPACE, "idle")


def inbox(name: str) -> str:
    return cluster.key(NAMESPACE, "in", name)


def outbox(command_id: str) -> str:
    return cluster.key(NAMESPACE, "out", command_id)


def waiting(user_id: int) -> str:
    return cluster.key(NAMESPACE, "waiting", user_id)


def keeper(donor_id: int) -> str:
    return f"{NAMESPACE}:keeper:{donor_id}"


def ci(repo_id: int) -> str:
    return f"{NAMESPACE}:ci:{repo_id}"


def counter(name: str) -> str:
    return cluster.key(NAMESPACE, "seq", name)
