"""Skill discovery, frontmatter, claims and the intake pipeline on fixtures. T2.1–T2.3, T2.7."""

from pathlib import Path

import pytest

from contracts.enums import ErrorCode
from core.archive import Limits
from core.intake.claims import RuleClaimExtractor
from core.intake.errors import IntakeError
from core.intake.local_source import LocalSource
from core.intake.pipeline import IntakeDeps, run_intake
from core.intake.skills import parse_frontmatter, skill_id

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def deps(tmp_path) -> IntakeDeps:
    return IntakeDeps(
        github=None, local=LocalSource(roots=[FIXTURES]), cache_root=tmp_path, limits=Limits()
    )


def _run(deps, fixture: str, ref=None):
    return run_intake(str(FIXTURES / fixture), ref, deps)


def test_t2_1_f1_one_candidate_with_name_and_description(deps):
    out = _run(deps, "F1_benign")
    [c] = out.candidates
    assert c.path == "SKILL.md" and c.name == "markdown-tidy"
    assert c.description.startswith("Formats markdown files consistently")
    assert c.skill_id == skill_id("SKILL.md") and c.files == ["FIXTURE.md"]
    assert len(out.commit_sha) == 40


def test_t2_2_f2_three_candidates_stable_ids(deps, tmp_path):
    first = _run(deps, "F2_multi")
    deps.cache_root = tmp_path / "other-cache"
    second = _run(deps, "F2_multi")
    assert [c.name for c in first.candidates] == ["heading-fix", "link-check", "table-tidy"]
    assert [c.skill_id for c in first.candidates] == [c.skill_id for c in second.candidates]
    assert len({c.skill_id for c in first.candidates}) == 3
    assert first.commit_sha == second.commit_sha


def test_t2_3_f3_no_skill(deps):
    with pytest.raises(IntakeError) as exc:
        _run(deps, "F3_no_skill")
    assert exc.value.code is ErrorCode.NO_SKILL
    assert "SKILL.md" in exc.value.detail and len(exc.value.detail) > 20


def test_t2_4_f8_warnings_reach_the_result(deps):
    out = _run(deps, "F8_symlink")
    assert len(out.candidates) == 1
    assert sum("refused link" in w for w in out.warnings) == 2


def test_t2_7_f10_claims_with_file_and_line(deps):
    out = _run(deps, "F10_claims")
    found = {(c.file, c.line): c.text for c in out.claims}
    assert "reduces AI detection to under 10%" in found[("README.md", 3)]
    assert "2x faster reviews" in found[("README.md", 4)]


def test_skill_resources_listed(deps):
    [c] = _run(deps, "F5_dangerous_shell").candidates
    assert c.files == ["FIXTURE.md", "scripts/setup.sh"]


def test_local_path_outside_allowed_roots_is_bad_url(deps, tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n")
    with pytest.raises(IntakeError) as exc:
        run_intake(str(tmp_path), None, deps)
    assert exc.value.code is ErrorCode.BAD_URL


def test_github_url_without_github_source_configured(deps):
    with pytest.raises(IntakeError) as exc:
        run_intake("https://github.com/acme/skill", None, deps)
    assert exc.value.code is ErrorCode.INTERNAL


@pytest.mark.parametrize(
    "text,name,desc",
    [
        ("---\nname: a\ndescription: b c\n---\nbody", "a", "b c"),
        ("---\nname: a\ndescription: >\n  folded\n  text\n---\n", "a", "folded text"),
        ("no frontmatter here", None, None),
        ("---\n: : not yaml [\n---\n", None, None),
        ("---\n- a list\n---\n", None, None),
    ],
)
def test_parse_frontmatter(text, name, desc):
    meta, _body = parse_frontmatter(text)
    assert meta.get("name") == name
    assert str(meta.get("description") or "").strip() == (desc or "")


def test_missing_name_falls_back_to_dir_with_warning(tmp_path):
    root = tmp_path / "repo"
    (root / "skills" / "pdf").mkdir(parents=True)
    (root / "skills" / "pdf" / "SKILL.md").write_text("just a body, no frontmatter\n")
    deps = IntakeDeps(github=None, local=LocalSource(roots=[tmp_path]), cache_root=tmp_path / "c")
    out = run_intake(str(root), None, deps)
    [c] = out.candidates
    assert c.name == "pdf" and c.description == ""
    assert any("frontmatter" in w for w in out.warnings)


@pytest.mark.parametrize(
    "line,is_claim",
    [
        ("Cuts token use by 40%.", True),
        ("Gives 3x more accurate answers", True),
        ("Reduces hallucinations in summaries", True),
        ("Detects prompt injection in incoming mail", True),
        ("Prevents secrets from leaking", True),
        ("Improves review quality", True),
        ("Install it with pip.", False),
        ("Use ATX headings with one space.", False),
        ("Version 2 of the helper", False),
    ],
)
def test_rule_claims(line, is_claim):
    claims = RuleClaimExtractor().extract("README.md", f"# Title\n\n{line}\n")
    assert bool(claims) is is_claim
    if is_claim:
        assert claims[0].line == 3 and claims[0].file == "README.md"


def test_claims_ignore_code_fences():
    text = "```\nreduces 99% of bugs\n```\n"
    assert RuleClaimExtractor().extract("README.md", text) == []
