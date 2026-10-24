"""Domain inventory: every URL host referenced by the skill. Informational, not a detector."""

import re
from dataclasses import dataclass
from pathlib import Path

URL = re.compile(r"\bhttps?://([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)", re.I)
NETWORK_WORDS = re.compile(
    r"\b(network|internet|online|web|http|https|api|url|fetch|download|upload|request|"
    r"remote|server|endpoint|webhook|cloud)\w*\b",
    re.I,
)
MAX_SCAN_BYTES = 1_000_000


@dataclass(frozen=True)
class DomainRef:
    domain: str
    file: str
    line: int
    undeclared: bool


def _text(path: Path) -> str | None:
    data = path.read_bytes()[:MAX_SCAN_BYTES]
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def domain_inventory(root: Path, files: list[str], description: str) -> list[DomainRef]:
    """First reference of each domain, sorted. root/files: the skill's own folder and files."""
    declares_network = bool(NETWORK_WORDS.search(description or ""))
    first: dict[str, DomainRef] = {}
    for rel in sorted(files):
        text = _text(root / rel)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            for host in URL.findall(line):
                host = host.lower().rstrip(".")
                if host not in first:
                    undeclared = not declares_network and host not in description.lower()
                    first[host] = DomainRef(host, rel, n, undeclared)
    return sorted(first.values(), key=lambda d: d.domain)
