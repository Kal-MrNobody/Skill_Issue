"""T2.6 GitHub URL forms → parsed or BAD_URL."""

import pytest

from contracts.enums import ErrorCode
from core.intake.errors import IntakeError
from core.intake.url import RepoRef, parse_github_url

GOOD = [
    ("https://github.com/acme/skill", RepoRef("acme", "skill")),
    ("https://github.com/acme/skill/", RepoRef("acme", "skill")),
    ("https://github.com/acme/skill.git", RepoRef("acme", "skill")),
    ("http://github.com/acme/skill", RepoRef("acme", "skill")),
    ("https://www.github.com/acme/skill", RepoRef("acme", "skill")),
    ("github.com/acme/skill", RepoRef("acme", "skill")),
    ("  https://github.com/acme/skill  ", RepoRef("acme", "skill")),
    ("https://github.com/Acme-Org/my.skill_v2", RepoRef("Acme-Org", "my.skill_v2")),
    ("https://github.com/acme/skill/tree/main", RepoRef("acme", "skill", ref="main")),
    ("https://github.com/acme/skill/tree/v1.2.0/", RepoRef("acme", "skill", ref="v1.2.0")),
    (
        "https://github.com/acme/skill/tree/main/skills/pdf",
        RepoRef("acme", "skill", ref="main", path="skills/pdf"),
    ),
    (
        "https://github.com/acme/skill/tree/0123456789abcdef0123456789abcdef01234567/x",
        RepoRef("acme", "skill", ref="0123456789abcdef0123456789abcdef01234567", path="x"),
    ),
    ("https://github.com/acme/skill#readme", RepoRef("acme", "skill")),
    ("https://github.com/acme/skill?tab=readme-ov-file", RepoRef("acme", "skill")),
]

BAD = [
    "",
    "not a url",
    "https://gitlab.com/acme/skill",
    "https://github.com/acme",
    "https://github.com/",
    "https://gist.github.com/acme/abc123",
    "https://github.com.evil.example.invalid/acme/skill",
    "https://evil.example.invalid/github.com/acme/skill",
    "ftp://github.com/acme/skill",
    "git@github.com:acme/skill.git",
    "https://github.com/acme/skill/blob/main/SKILL.md",
    "https://github.com/acme/skill/tree/main/../../etc",
    "https://github.com/acme/sk ill",
    "https://user:pass@github.com/acme/skill",
    "https://github.com:8443/acme/skill",
    "https://github.com/acme/skill/tree",
    "https://github.com/../skill",
]


@pytest.mark.parametrize("url,expected", GOOD, ids=[g[0] or "empty" for g in GOOD])
def test_t2_6_parses(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize("url", BAD, ids=[b or "empty" for b in BAD])
def test_t2_6_bad_url(url):
    with pytest.raises(IntakeError) as exc:
        parse_github_url(url)
    assert exc.value.code is ErrorCode.BAD_URL
    assert exc.value.detail  # human-readable


def test_repo_ref_display():
    assert RepoRef("acme", "skill").display == "github.com/acme/skill"
