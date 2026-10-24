"""Step 3 integration: the real scanner on every fixture, and the security agent in the flow."""

import asyncio
import shutil
from pathlib import Path

import pytest

from agents.runtime import running
from agents.security.scanner import CliScanner, default_command
from contracts.enums import GateDecision, JobState
from core.archive import Limits
from core.flow import FlowConfig
from core.intake.local_source import LocalSource
from core.intake.pipeline import IntakeDeps
from core.security.normalize import normalize_sarif
from core.security.pipeline import ScanDeps

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures"
SKILL_DIRS = sorted(p.parent for p in FIXTURES.rglob("SKILL.md"))


def test_scanner_is_installed():
    assert shutil.which(default_command()[0]), (
        "skill-scanner not found: uv tool install cisco-ai-skill-scanner==2.2.2"
    )


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_t3_4_real_scanner_on_every_fixture(skill_dir, tmp_path):
    # scan a copy without the links: the scanner only ever sees extracted snapshots
    copy = tmp_path / "skill"
    shutil.copytree(
        skill_dir,
        copy,
        symlinks=True,
        ignore=lambda d, names: [n for n in names if (Path(d) / n).is_symlink()],
    )
    sarif = CliScanner(timeout=120).scan(copy)
    findings = normalize_sarif(sarif, ".")
    assert all(f.file and f.line >= 1 for f in findings)


def _deps(tmp_path):
    local = LocalSource(roots=[FIXTURES])
    intake = IntakeDeps(github=None, local=local, cache_root=tmp_path, limits=Limits())
    scan = ScanDeps(github=None, local=local, cache_root=tmp_path, scanner=CliScanner(timeout=120))
    return intake, scan


@pytest.mark.parametrize(
    "fixture,gate,final",
    [
        ("F1_benign", GateDecision.STANDARD, JobState.AWAITING_RUN_CLICK),
        ("F5_dangerous_shell", GateDecision.RESTRICTED, JobState.AWAITING_RUN_CLICK),
        ("F11_test_tamper", GateDecision.BLOCK, JobState.DONE),
    ],
)
async def test_real_intake_and_scan_in_the_flow(system_factory, tmp_path, fixture, gate, final):
    intake, scan = _deps(tmp_path)
    system = system_factory(cfg=FlowConfig(), intake_deps=intake, scan_deps=scan)
    orch = system.orchestrator
    async with running(system.apps):
        job_id = orch.submit(str(FIXTURES / fixture))
        for _ in range(600):
            await asyncio.sleep(0.1)
            if orch.store.get(job_id).state in (
                JobState.AWAITING_RUN_CLICK,
                JobState.DONE,
                JobState.FAILED,
            ):
                break
    job = orch.store.get(job_id)
    assert job.state is final, job.failure
    assert job.scan["gate"] == gate
    assert job.scan["provenance"]["tool_versions"]["cisco-ai-skill-scanner"] == "2.2.2"
    if gate is GateDecision.BLOCK:
        assert job.bench is None  # security-only report, no benchmark
