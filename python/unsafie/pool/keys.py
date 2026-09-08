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


def log(command_id: str) -> str:
    return cluster.key(NAMESPACE, "log", command_id)


def hold(name: str) -> str:
    return cluster.key(NAMESPACE, "hold", name)


def pending() -> str:
    return cluster.key(NAMESPACE, "pending")


def keeper(donor_id: int) -> str:
    return f"{NAMESPACE}:keeper:{donor_id}"


def ci(repo_id: int) -> str:
    return f"{NAMESPACE}:ci:{repo_id}"


def counter(name: str) -> str:
    return cluster.key(NAMESPACE, "seq", name)


def desktop(slug: str) -> str:
    return cluster.key(NAMESPACE, "desktop", slug)


def tunnel(channel_id: str) -> str:
    return cluster.key(NAMESPACE, "tun", channel_id)


def tunnel_ready(channel_id: str) -> str:
    return cluster.key(NAMESPACE, "tun", channel_id, "ready")


def tunnel_up(channel_id: str) -> str:
    return cluster.key(NAMESPACE, "tun", channel_id, "up")


def tunnel_down(channel_id: str) -> str:
    return cluster.key(NAMESPACE, "tun", channel_id, "down")
