from dataclasses import dataclass

from unsafie.settings import settings


@dataclass(frozen=True)
class NodeInfo:
    id: str
    priority: int
    mesh_ip: str
    domain: str

    @property
    def gossip_addr(self) -> tuple[str, int]:
        return self.mesh_ip, settings.gossip_port


def this_node() -> NodeInfo:
    return NodeInfo(
        id=settings.node_id,
        priority=settings.node_priority,
        mesh_ip=settings.node_mesh_ip,
        domain=settings.node_domain,
    )
