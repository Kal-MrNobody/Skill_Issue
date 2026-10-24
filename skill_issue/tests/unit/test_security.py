"""Security: SARIF normalization (golden files), gate policy, fail-safe scans, domain inventory."""

import itertools
import json
from pathlib import Path

import pytest

from contracts.enums import Bucket, ErrorCode, GateDecision, Severity
from core.archive import Limits
from core.intake.local_source import LocalSource
from core.security.domains import domain_inventory
from core.security.gate import gate_for
from core.security.normalize import NormFinding, normalize_sarif
from core.security.pipeline import ScanDeps, ScannerError, run_scan

TESTS = Path(__file__).parents[1]
GOLDEN = TESTS / "golden" / "sarif"
FIXTURES = TESTS / "fixtures"


def _golden(name: str) -> dict:
    return json.loads((GOLDEN / f"{name}.sarif").read_text())


def _keyed(findings):
    return {(f.rule_id, f.file, f.line): (f.bucket, f.severity) for f in findings}


# --- T3.1 normalization against golden SARIF ------------------------------


def test_t3_1_f5_dangerous_command_with_file_and_line():
    found = _keyed(normalize_sarif(_golden("F5_dangerous_shell"), skill_folder="."))
    assert found[("CORRELATED_NETWORK_EXECUTION_FLOW", "scripts/setup.sh", 4)] == (
        Bucket.DANGEROUS_COMMAND,
        Severity.HIGH,
    )
    assert found[("MANIFEST_MISSING_LICENSE", "SKILL.md", 1)] == (Bucket.OTHER, Severity.INFO)


def test_t3_1_f6_network_findings():
    found = _keyed(normalize_sarif(_golden("F6_undeclared_network"), skill_folder="."))
    assert found[("DATA_EXFIL_NETWORK_REQUESTS", "scripts/format.py", 7)] == (
        Bucket.NETWORK,
        Severity.MEDIUM,
    )
    assert found[("DATA_EXFIL_NETWORK_REQUESTS", "scripts/format.py", 11)][0] is Bucket.NETWORK
    assert found[("TOOL_ABUSE_UNDECLARED_NETWORK", "SKILL.md", 1)][0] is Bucket.NETWORK


def test_t3_1_f11_prompt_injection_critical():
    found = _keyed(normalize_sarif(_golden("F11_test_tamper"), skill_folder="."))
    assert found[("YARA_prompt_injection_generic", "SKILL.md", 2)] == (
        Bucket.PROMPT_INJECTION,
        Severity.CRITICAL,
    )


def test_t3_1_paths_are_made_repo_relative():
    findings = normalize_sarif(_golden("F5_dangerous_shell"), skill_folder="skills/boot")
    assert {f.file for f in findings} == {"skills/boot/SKILL.md", "skills/boot/scripts/setup.sh"}


def test_t3_1_f1_only_informational():
    findings = normalize_sarif(_golden("F1_benign"), skill_folder=".")
    assert findings and all(f.severity is Severity.INFO for f in findings)


def test_dedupe_identical_findings():
    sarif = _golden("F5_dangerous_shell")
    sarif["runs"][0]["results"] *= 2
    once = normalize_sarif(_golden("F5_dangerous_shell"), ".")
    assert normalize_sarif(sarif, ".") == once


def test_unknown_category_and_missing_severity_fall_back():
    sarif = {
        "runs": [
            {
                "results": [
                    {
                        "ruleId": "X",
                        "level": "error",
                        "message": {"text": "m"},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}}}],
                    }
                ]
            }
        ]
    }
    [f] = normalize_sarif(sarif, ".")
    assert (f.bucket, f.severity, f.file, f.line) == (Bucket.OTHER, Severity.HIGH, "a.py", 1)


def test_malformed_sarif_raises_scanner_error():
    with pytest.raises(ScannerError):
        normalize_sarif({"runs": "nope"}, ".")


# --- T3.6 every finding has a file and a line -----------------------------


@pytest.mark.parametrize("name", [p.stem for p in GOLDEN.glob("*.sarif")])
def test_t3_6_every_finding_has_file_and_line(name):
    for f in normalize_sarif(_golden(name), "."):
        assert f.file and isinstance(f.line, int) and f.line >= 1
        assert f.message and f.rule_id and f.source == "skill-scanner"


# --- T3.2 gate policy table ------------------------------------------------


def _f(sev: Severity) -> NormFinding:
    return NormFinding(Bucket.OTHER, sev, "SKILL.md", 1, "m", "R", "skill-scanner")


def _expected_gate(sevs) -> GateDecision:
    if Severity.CRITICAL in sevs:
        return GateDecision.BLOCK
    if Severity.HIGH in sevs or Severity.MEDIUM in sevs:
        return GateDecision.RESTRICTED
    return GateDecision.STANDARD


ALL_MIXES = [
    combo for n in range(len(Severity) + 1) for combo in itertools.combinations(list(Severity), n)
]


@pytest.mark.parametrize("sevs", ALL_MIXES, ids=lambda s: "+".join(s) or "none")
def test_t3_2_gate_covers_every_severity_mix(sevs):
    assert gate_for([_f(s) for s in sevs], scan_failed=False) is _expected_gate(set(sevs))


@pytest.mark.parametrize(
    "sevs,expected",
    [
        ((), GateDecision.STANDARD),
        ((Severity.INFO, Severity.LOW), GateDecision.STANDARD),
        ((Severity.MEDIUM,), GateDecision.RESTRICTED),
        ((Severity.HIGH, Severity.LOW), GateDecision.RESTRICTED),
        ((Severity.CRITICAL, Severity.INFO), GateDecision.BLOCK),
    ],
)
def test_t3_2_gate_examples(sevs, expected):
    assert gate_for([_f(s) for s in sevs], scan_failed=False) is expected


def test_t3_2_failed_scan_is_restricted_never_standard():
    assert gate_for([], scan_failed=True) is GateDecision.RESTRICTED
    assert gate_for([_f(Severity.CRITICAL)], scan_failed=True) is GateDecision.BLOCK


# --- T3.3 scanner timeout / crash → SCAN_FAILED + RESTRICTED ----------------


class FakeScanner:
    def __init__(self, sarif=None, error: ScannerError | None = None):
        self.sarif, self.error, self.calls = sarif, error, []

    version = "fake-1.0"

    def scan(self, skill_dir: Path) -> dict:
        self.calls.append(skill_dir)
        if self.error:
            raise self.error
        return self.sarif


def _deps(tmp_path, scanner) -> ScanDeps:
    return ScanDeps(
        github=None,
        local=LocalSource(roots=[FIXTURES]),
        cache_root=tmp_path,
        limits=Limits(),
        scanner=scanner,
    )


def _scan(tmp_path, fixture, scanner):
    src = LocalSource(roots=[FIXTURES])
    path = str(FIXTURES / fixture)
    sha = src.resolve(src.ref_for(path))
    return run_scan(path, sha, "SKILL.md", _deps(tmp_path, scanner))


@pytest.mark.parametrize("kind", ["timeout", "crash"])
def test_t3_3_scanner_failure_fails_safe(tmp_path, kind):
    out = _scan(tmp_path, "F1_benign", FakeScanner(error=ScannerError(kind, "boom")))
    assert out.scan_error is ErrorCode.SCAN_FAILED
    assert out.gate is GateDecision.RESTRICTED and out.findings == []


def test_scan_runs_on_the_skill_folder_of_the_snapshot(tmp_path):
    scanner = FakeScanner(sarif=_golden("F5_dangerous_shell"))
    out = _scan(tmp_path, "F5_dangerous_shell", scanner)
    [skill_dir] = scanner.calls
    assert (skill_dir / "SKILL.md").is_file() and skill_dir.is_relative_to(tmp_path)
    assert out.gate is GateDecision.RESTRICTED and out.scan_error is None
    assert out.scanner_version == "fake-1.0"


def test_f11_golden_blocks(tmp_path):
    out = _scan(tmp_path, "F11_test_tamper", FakeScanner(sarif=_golden("F11_test_tamper")))
    assert out.gate is GateDecision.BLOCK


# --- T3.5 domain inventory --------------------------------------------------


def test_t3_5_f6_domain_undeclared(tmp_path):
    out = _scan(tmp_path, "F6_undeclared_network", FakeScanner(sarif=_golden("F1_benign")))
    assert "api.example.invalid" in out.domains
    assert "api.example.invalid" in out.undeclared_domains


def test_domains_declared_when_description_mentions_network(tmp_path):
    (tmp_path / "SKILL.md").write_text(
        "---\nname: x\ndescription: Fetches weather from a web API\n---\n"
        "Call https://weather.example.invalid/v1 and summarise.\n"
    )
    inv = domain_inventory(tmp_path, ["SKILL.md"], "Fetches weather from a web API")
    assert [(d.domain, d.undeclared) for d in inv] == [("weather.example.invalid", False)]
    assert inv[0].file == "SKILL.md" and inv[0].line == 5


def test_domain_inventory_dedupes_and_ignores_non_text(tmp_path):
    (tmp_path / "a.md").write_text("see https://a.example.invalid and http://a.example.invalid/x\n")
    (tmp_path / "b.bin").write_bytes(b"\0\xffhttps://b.example.invalid")
    inv = domain_inventory(tmp_path, ["a.md", "b.bin"], "formats text")
    assert [d.domain for d in inv] == ["a.example.invalid"]
