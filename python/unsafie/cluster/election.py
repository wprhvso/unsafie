import logging
import time

from unsafie import events
from unsafie.cluster import arbiter, leader
from unsafie.cluster.gossip import Gossip
from unsafie.cluster.node import this_node
from unsafie.settings import settings

logger = logging.getLogger(__name__)


def _lsn_int(lsn: str) -> int:
    try:
        hi, lo = lsn.split("/")
        return (int(hi, 16) << 32) | int(lo, 16)
    except (ValueError, AttributeError):
        return 0


class Election:
    def __init__(self) -> None:
        self.node = this_node()
        self.term = 0
        self.leader: str | None = None
        self.role = "replica"
        self.lease_until = 0.0
        self.last_change = 0.0
        self.gossip: Gossip | None = None
        self.local_lsn = "0/0"

    @property
    def cluster_size(self) -> int:
        return len(settings.peers) + 1

    @property
    def is_leader(self) -> bool:
        return self.role == "leader"

    def snapshot(self) -> dict:
        return {
            "node": self.node.id,
            "term": self.term,
            "leader": self.leader,
            "role": self.role,
            "lsn": self.local_lsn,
            "priority": self.node.priority,
            "healthy": True,
        }

    async def tick(self) -> None:
        if self.gossip is None:
            return
        self.gossip.broadcast(self.snapshot())
        peers = self.gossip.alive_peers()
        seen = len(peers) + 1
        majority = self.cluster_size // 2 + 1

        if self.is_leader:
            await self._as_leader(seen, majority)
            return

        leader_alive = any(p.node == self.leader and p.alive for p in peers)
        if self.leader and leader_alive:
            return
        await self._maybe_campaign(peers, seen, majority)

    async def _as_leader(self, seen: int, majority: int) -> None:
        if seen >= majority:
            self.lease_until = time.monotonic() + settings.election_lease
            return
        if await arbiter.webhook_oracle():
            self.lease_until = time.monotonic() + settings.election_lease
            return
        if time.monotonic() > self.lease_until:
            await self._step_down()

    async def _maybe_campaign(self, peers, seen: int, majority: int) -> None:
        if time.monotonic() - self.last_change < settings.election_min_term_interval:
            return
        candidates = peers
        my_lsn = _lsn_int(self.local_lsn)
        if any(_lsn_int(p.lsn) > my_lsn for p in candidates):
            return
        higher_priority_alive = any(
            p.priority > self.node.priority and _lsn_int(p.lsn) >= my_lsn for p in candidates
        )
        if higher_priority_alive:
            return

        votes = 1 + sum(1 for p in peers if p.term <= self.term)
        won_peers = seen >= majority and votes >= majority

        if won_peers:
            await self._win(self.term + 1, "peer majority")
            return

        content, sha = await arbiter.read_cas()
        oracle = await arbiter.webhook_oracle()
        arbiter_votes = (1 if oracle else 0) + (1 if content is not None else 0)
        if arbiter_votes < 2:
            return
        new_term = max(self.term, (content or {}).get("term", 0)) + 1
        if await arbiter.claim_cas(new_term, self.node.id, "arbiter", sha):
            await self._win(new_term, "arbiter")

    async def _win(self, term: int, reason: str) -> None:
        self.term = term
        self.leader = self.node.id
        self.role = "leader"
        self.last_change = time.monotonic()
        self.lease_until = time.monotonic() + settings.election_lease
        await leader.record(term, self.node.id, reason, durable=True)
        await leader.on_acquire(term, reason)
        events.publish("cluster.leader", node=self.node.id, term=term, reason=reason)

    async def _step_down(self) -> None:
        term = self.term
        self.role = "replica"
        self.leader = None
        self.last_change = time.monotonic()
        await leader.on_release(term)
        events.publish("cluster.stepdown", node=self.node.id, term=term)


election = Election()
