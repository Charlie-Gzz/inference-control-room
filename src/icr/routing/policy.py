"""Reference routing policies in Python. Mirrors `router/policies/` in Go.

Used by the shared test vectors and by quick simulations. The production router is Go.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field

from icr.routing.prefix import canonical_text, prefix_hashes

POLICIES = ("round-robin", "least-loaded", "prefix-aware")


@dataclass
class RouterConfig:
    chunk_size: int = 256  # bytes of prompt text per hashed chunk
    max_chunks: int = 128  # hash at most this many chunks per request
    table_chunks: int = 4096  # prefix hashes remembered per replica (LRU)
    load_factor: float = 1.5  # a replica is overloaded above load_factor x fair share
    min_bound: int = 4  # ... but never below this many outstanding requests


@dataclass
class Decision:
    replica: int
    reason: str  # round-robin | least-loaded | prefix-hit | prefix-overloaded | no-prefix
    matched_chunks: int = 0
    loads: list[int] = field(default_factory=list)  # outstanding per live replica, at decision


class Router:
    """Routing state: live replicas, outstanding requests, and the per-replica prefix table."""

    def __init__(self, replicas: int, policy: str, config: RouterConfig | None = None):
        self.config = config or RouterConfig()
        self.policy = policy
        self.live = list(range(replicas))
        self.outstanding = {i: 0 for i in self.live}
        self.tables: dict[int, OrderedDict[int, None]] = {i: OrderedDict() for i in self.live}
        self.rr_next = 0

    def set_live(self, live: list[int]) -> None:
        self.live = sorted(live)
        for i in self.live:
            self.outstanding.setdefault(i, 0)
            self.tables.setdefault(i, OrderedDict())
        for i in list(self.tables):
            if i not in self.live:
                self.tables[i].clear()  # a stopped replica loses its cache

    def reset(self) -> None:
        for table in self.tables.values():
            table.clear()
        self.rr_next = 0

    def _least_loaded(self) -> int:
        return min(self.live, key=lambda i: (self.outstanding[i], i))

    def _bound(self) -> int:
        total = sum(self.outstanding[i] for i in self.live)
        fair = (total + 1) / len(self.live)
        return max(self.config.min_bound, math.ceil(self.config.load_factor * fair))

    def _match(self, replica: int, hashes: list[int]) -> int:
        table = self.tables[replica]
        n = 0
        for h in hashes:
            if h not in table:
                break
            n += 1
        return n

    def route(self, messages: list[dict]) -> Decision:
        """Pick a replica for this request and count it as outstanding."""
        loads = [self.outstanding[i] for i in self.live]
        hashes: list[int] = []
        if self.policy == "round-robin":
            replica = self.live[self.rr_next % len(self.live)]
            self.rr_next += 1
            decision = Decision(replica, "round-robin", 0, loads)
        elif self.policy == "least-loaded":
            decision = Decision(self._least_loaded(), "least-loaded", 0, loads)
        else:
            c = self.config
            hashes = prefix_hashes(canonical_text(messages), c.chunk_size, c.max_chunks)
            decision = self._prefix_aware(hashes, loads)
        self.outstanding[decision.replica] += 1
        if hashes:
            self._remember(decision.replica, hashes)
        return decision

    def _prefix_aware(self, hashes: list[int], loads: list[int]) -> Decision:
        matches = {i: self._match(i, hashes) for i in self.live}
        best = max(matches.values(), default=0)
        if best == 0:
            return Decision(self._least_loaded(), "no-prefix", 0, loads)
        bound = self._bound()
        # Longest match first; ties go to the less loaded replica, then the lower index.
        ranked = sorted(self.live, key=lambda i: (-matches[i], self.outstanding[i], i))
        for i in ranked:
            if matches[i] == 0:
                break
            if self.outstanding[i] <= bound:
                return Decision(i, "prefix-hit", matches[i], loads)
        return Decision(self._least_loaded(), "prefix-overloaded", best, loads)

    def _remember(self, replica: int, hashes: list[int]) -> None:
        # Touch the longest prefix first, so short (widely shared) prefixes are evicted last.
        table = self.tables[replica]
        for h in reversed(hashes):
            table[h] = None
            table.move_to_end(h)
        while len(table) > self.config.table_chunks:
            table.popitem(last=False)

    def finish(self, replica: int) -> None:
        self.outstanding[replica] = max(0, self.outstanding[replica] - 1)
