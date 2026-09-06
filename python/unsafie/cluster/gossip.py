import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from unsafie.cluster.node import this_node
from unsafie.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class PeerState:
    node: str
    term: int = 0
    leader: str | None = None
    role: str | None = None
    lsn: str = "0/0"
    priority: int = 0
    healthy: bool = True
    at: float = field(default_factory=time.monotonic)

    @property
    def alive(self) -> bool:
        return time.monotonic() - self.at < settings.election_dead_after


class Gossip(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.peers: dict[str, PeerState] = {}
        self.transport: asyncio.DatagramTransport | None = None
        self.local: dict = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            msg = json.loads(data)
        except ValueError:
            return
        node = msg.get("node")
        if not node or node == this_node().id:
            return
        self.peers[node] = PeerState(
            node=node,
            term=msg.get("term", 0),
            leader=msg.get("leader"),
            role=msg.get("role"),
            lsn=msg.get("lsn", "0/0"),
            priority=msg.get("priority", 0),
            healthy=msg.get("healthy", True),
        )

    def broadcast(self, state: dict) -> None:
        self.local = state
        if self.transport is None:
            return
        payload = json.dumps(state).encode()
        for peer in settings.peers:
            try:
                self.transport.sendto(payload, (peer, settings.gossip_port))
            except OSError as e:
                logger.debug("gossip send %s: %s", peer, e)

    def alive_peers(self) -> list[PeerState]:
        return [p for p in self.peers.values() if p.alive]


async def bind() -> Gossip:
    loop = asyncio.get_running_loop()
    _, protocol = await loop.create_datagram_endpoint(
        Gossip, local_addr=("0.0.0.0", settings.gossip_port)
    )
    logger.info("gossip bound on %s", settings.gossip_port)
    return protocol  # type: ignore[return-value]
