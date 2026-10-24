"""ASI:One echo-loop guards: duplicates, our own replies coming back, cooldown, job cap."""

from collections import OrderedDict
from difflib import SequenceMatcher
from enum import StrEnum


class Verdict(StrEnum):
    ACCEPT = "ACCEPT"
    DUPLICATE = "DUPLICATE"  # same text from the same sender inside the window: drop silently
    ECHO = "ECHO"  # our own reply (or an LLM rewrite of it) sent back: drop silently
    COOLDOWN = "COOLDOWN"  # new job too soon after the last one: one polite reply
    TOO_MANY = "TOO_MANY"  # too many active jobs for this sender: one polite reply


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def emoji_count(text: str) -> int:
    return sum(1 for ch in text if ord(ch) >= 0x1F000 or 0x2600 <= ord(ch) <= 0x27BF)


class EchoGuard:
    def __init__(
        self,
        duplicate_window: float = 20,
        cooldown: float = 3,
        max_active_jobs: int = 5,
        max_senders: int = 10_000,
        echo_window: float = 900,
        similarity: float = 0.85,
    ) -> None:
        self.duplicate_window = duplicate_window
        self.cooldown = cooldown
        self.max_active_jobs = max_active_jobs
        self.max_senders = max_senders
        self.echo_window = echo_window
        self.similarity = similarity
        self._seen: OrderedDict[str, dict[str, float]] = OrderedDict()
        self._replies: dict[str, list[tuple[str, float]]] = {}
        self._last_job: dict[str, float] = {}

    def check(self, sender: str, text: str, now: float) -> Verdict:
        norm = normalize(text)
        if emoji_count(text) >= 3 or self._is_echo(sender, norm, now):
            return Verdict.ECHO
        seen = self._seen.setdefault(sender, {})
        self._seen.move_to_end(sender)
        for key, ts in list(seen.items()):
            if now - ts > self.duplicate_window:
                del seen[key]
        if norm in seen:
            return Verdict.DUPLICATE
        seen[norm] = now
        while len(self._seen) > self.max_senders:
            old, _ = self._seen.popitem(last=False)
            self._replies.pop(old, None)
            self._last_job.pop(old, None)
        return Verdict.ACCEPT

    def _is_echo(self, sender: str, norm: str, now: float) -> bool:
        for reply, ts in self._replies.get(sender, []):
            if now - ts > self.echo_window:
                continue
            if reply in norm or SequenceMatcher(None, reply, norm).ratio() >= self.similarity:
                return True
        return False

    def record_reply(self, sender: str, text: str, now: float) -> None:
        replies = self._replies.setdefault(sender, [])
        replies.append((normalize(text), now))
        del replies[:-5]

    def may_start_job(self, sender: str, active_jobs: int, now: float) -> Verdict:
        if active_jobs >= self.max_active_jobs:
            return Verdict.TOO_MANY
        last = self._last_job.get(sender)
        if last is not None and now - last < self.cooldown:
            return Verdict.COOLDOWN
        return Verdict.ACCEPT

    def job_started(self, sender: str, now: float) -> None:
        self._last_job[sender] = now
