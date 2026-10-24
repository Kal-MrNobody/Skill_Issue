"""T0.4 each inert fixture repo contains what its scenario needs. Files are read, never run."""

import os
import re
import stat
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"

# id -> (folder, number of SKILL.md files)
EXPECTED = {
    "F1": ("F1_benign", 1),
    "F2": ("F2_multi", 3),
    "F3": ("F3_no_skill", 0),
    "F4": ("F4_hidden_instructions", 1),
    "F5": ("F5_dangerous_shell", 1),
    "F6": ("F6_undeclared_network", 1),
    "F7": ("F7_canary_reader", 1),
    "F8": ("F8_symlink", 1),
    "F10": ("F10_claims", 1),
    "F11": ("F11_test_tamper", 1),
}

URL_HOST = re.compile(r"https?://([A-Za-z0-9.-]+)")


def _files(folder: str) -> list[Path]:
    root = FIXTURES / folder
    return [p for p in root.rglob("*") if not p.is_symlink() and p.is_file()]


def _skill_mds(folder: str) -> list[Path]:
    return [p for p in _files(folder) if p.name == "SKILL.md"]


def _text(folder: str, rel: str) -> str:
    return (FIXTURES / folder / rel).read_text(encoding="utf-8")


def _all_text(folder: str) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _files(folder))


@pytest.mark.parametrize("fid", EXPECTED)
def test_fixture_has_fixture_md(fid):
    folder, _ = EXPECTED[fid]
    doc = FIXTURES / folder / "FIXTURE.md"
    assert doc.is_file()
    body = doc.read_text(encoding="utf-8")
    assert fid in body and "Expected" in body


@pytest.mark.parametrize("fid", EXPECTED)
def test_skill_md_count(fid):
    folder, count = EXPECTED[fid]
    assert len(_skill_mds(folder)) == count


@pytest.mark.parametrize("fid", EXPECTED)
def test_skill_md_has_frontmatter(fid):
    folder, _ = EXPECTED[fid]
    for p in _skill_mds(folder):
        text = p.read_text(encoding="utf-8")
        assert re.match(r"---\nname: \S+\ndescription: .+\n", text), p


@pytest.mark.parametrize("fid", EXPECTED)
def test_inert_reserved_domains_only(fid):
    folder, _ = EXPECTED[fid]
    for host in URL_HOST.findall(_all_text(folder)):
        assert host.endswith(".example.invalid"), host


@pytest.mark.parametrize("fid", EXPECTED)
def test_no_executable_bits(fid):
    folder, _ = EXPECTED[fid]
    for p in _files(folder):
        assert not p.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), p


def test_f1_benign_has_no_scripts():
    assert {p.name for p in _files("F1_benign")} == {"SKILL.md", "FIXTURE.md"}


def test_f2_three_distinct_skills():
    names = {
        re.search(r"^name: (\S+)", p.read_text(), re.M).group(1) for p in _skill_mds("F2_multi")
    }
    assert len(names) == 3


def test_f3_readme_only():
    assert {p.name for p in _files("F3_no_skill")} == {"README.md", "FIXTURE.md"}


def test_f4_hidden_instruction_in_html_comment():
    comment = re.search(r"<!--(.*?)-->", _text("F4_hidden_instructions", "SKILL.md"), re.S)
    assert comment
    assert "collector.example.invalid" in comment.group(1)
    assert "ignore" in comment.group(1).lower()


def test_f5_pipe_to_shell_and_recursive_delete():
    script = _text("F5_dangerous_shell", "scripts/setup.sh")
    assert re.search(r"curl [^\n|]*https://get\.example\.invalid[^\n|]*\|\s*(ba)?sh", script)
    assert re.search(r"rm -rf /tmp/\S+", script)


def test_f6_description_mismatch_and_post():
    skill = _text("F6_undeclared_network", "SKILL.md")
    script = _text("F6_undeclared_network", "scripts/format.py")
    assert "markdown" in skill.lower() and "network" not in skill.lower()
    assert "https://api.example.invalid" in script and "POST" in script


def test_f7_reads_aws_credentials():
    script = _text("F7_canary_reader", "scripts/check_env.py")
    assert ".aws" in script and "credentials" in script
    assert "example.invalid" not in script  # nothing obviously malicious for static to see


def test_f8_symlinks():
    root = FIXTURES / "F8_symlink"
    links = {p.name: os.readlink(p) for p in root.iterdir() if p.is_symlink()}
    assert links == {"hostname": "/etc/hostname", "escape": "../../outside"}


def test_f10_claims_on_known_lines():
    lines = _text("F10_claims", "README.md").splitlines()
    doc = _text("F10_claims", "FIXTURE.md")
    for claim in ("reduces AI detection to under 10%", "2x faster reviews"):
        idx = next(i for i, line in enumerate(lines) if claim in line)
        assert f"README.md:{idx + 1}" in doc, claim


def test_f11_tells_agent_to_edit_tests():
    text = _text("F11_test_tamper", "SKILL.md").lower()
    assert "test" in text and "until" in text and "pass" in text


def test_f9_is_not_committed():
    assert not list(FIXTURES.glob("F9*"))
