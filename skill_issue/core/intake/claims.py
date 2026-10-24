"""Claims extraction v1: rules over README and SKILL.md lines. Seam for an LLM extractor later."""

import re
from dataclasses import dataclass
from typing import Protocol

MAX_CLAIM_CHARS = 300

PERCENT = re.compile(r"\b\d+(?:\.\d+)?\s?%")
MULTIPLIER = re.compile(r"\b\d+(?:\.\d+)?\s?[x×]\b", re.I)
VERB = re.compile(r"\b(reduc|improv|detect|prevent)\w*\b", re.I)


@dataclass(frozen=True)
class ClaimRecord:
    text: str
    file: str
    line: int


class ClaimExtractor(Protocol):
    def extract(self, file: str, text: str) -> list[ClaimRecord]: ...


class RuleClaimExtractor:
    def extract(self, file: str, text: str) -> list[ClaimRecord]:
        claims, in_fence = [], False
        for n, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if line.startswith("```") or line.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence or not line or line.startswith("#"):
                continue
            if PERCENT.search(line) or MULTIPLIER.search(line) or VERB.search(line):
                claims.append(ClaimRecord(line[:MAX_CLAIM_CHARS], file, n))
        return claims


def is_claim_source(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name == "skill.md" or (name.startswith("readme") and name.endswith(".md"))
