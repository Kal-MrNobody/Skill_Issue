"""Worker-side request guard: sender allowlist plus duplicate suppression."""

from collections import OrderedDict
from enum import StrEnum


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    ROGUE = "ROGUE"  # sender is not the orchestrator
    DUPLICATE = "DUPLICATE"  # same job_id + step + attempt already handled


class RequestGuard:
    def __init__(self, allowed: set[str], max_keys: int = 10_000) -> None:
        self.allowed = set(allowed)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._max = max_keys

    def check(self, sender: str, key: str) -> Decision:
        if sender not in self.allowed:
            return Decision.ROGUE
        if key in self._seen:
            return Decision.DUPLICATE
        self._seen[key] = None
        if len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return Decision.ACCEPT
