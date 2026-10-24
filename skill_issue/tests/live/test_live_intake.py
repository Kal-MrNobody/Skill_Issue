"""T2.8 (live): a real public skill repo resolves to a 40-character commit SHA."""

import os
import re

import pytest

from agents.sources import GitHubSource
from core.archive import Limits
from core.intake.pipeline import IntakeDeps, run_intake

pytestmark = pytest.mark.live

PUBLIC_SKILL_REPO = "https://github.com/anthropics/skills"


def test_t2_8_real_repo_pins_commit(tmp_path):
    deps = IntakeDeps(
        github=GitHubSource(token=os.environ.get("GITHUB_TOKEN")),
        local=None,
        cache_root=tmp_path,
        limits=Limits(),
    )
    out = run_intake(PUBLIC_SKILL_REPO, None, deps)
    assert re.fullmatch(r"[0-9a-f]{40}", out.commit_sha)
    assert out.candidates
