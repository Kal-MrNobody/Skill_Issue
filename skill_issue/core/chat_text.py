"""Pull a repo reference out of a free-text chat message."""

import re

from core.intake.errors import IntakeError
from core.intake.url import parse_github_url

GITHUB = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"
    r"(?:/tree/[^\s<>()\[\]\"'`]+)?",
    re.I,
)
FIXTURE_PATH = re.compile(r"(?<![\w/.-])((?:\.?/)?(?:[\w.-]+/)*tests/fixtures/[\w.-]+)")
TRAILING = ".,;:!?"

HELP_TEXT = (
    "Send me a link to an AI agent skill on GitHub (a repository with a SKILL.md), "
    "for example: https://github.com/anthropics/skills . I'll check whether it can be "
    "trusted and, if you want, whether it actually helps."
)


def extract_repo_url(text: str, dev_mode: bool) -> str | None:
    for m in GITHUB.finditer(text or ""):
        url = m.group(0).rstrip(TRAILING)
        try:
            parse_github_url(url)
        except IntakeError:
            continue
        return url
    if dev_mode:
        m = FIXTURE_PATH.search(text or "")
        if m:
            path = m.group(1).rstrip(TRAILING)
            return path if path.startswith(("/", "./")) else "./" + path
    return None
