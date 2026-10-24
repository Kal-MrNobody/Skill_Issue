"""Step 2: the real intake agent inside the agent flow (fixtures via LocalSource)."""

import asyncio
from pathlib import Path

import pytest

from agents.runtime import running
from contracts.enums import ErrorCode, JobState
from core.archive import Limits
from core.flow import FlowConfig
from core.intake.local_source import LocalSource
from core.intake.pipeline import IntakeDeps

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def deps(tmp_path):
    return IntakeDeps(
        github=None, local=LocalSource(roots=[FIXTURES]), cache_root=tmp_path, limits=Limits()
    )


async def test_f1_flows_to_done_with_real_intake(system_factory, deps):
    system = system_factory(cfg=FlowConfig(auto_run=True), intake_deps=deps)
    async with running(system.apps):
        job_id = system.orchestrator.submit(str(FIXTURES / "F1_benign"))
        job = await system.orchestrator.wait(job_id, timeout=10)
    assert job.state is JobState.DONE
    assert [c["name"] for c in job.candidates] == ["markdown-tidy"]
    assert len(job.commit_sha) == 40 and job.scan["commit_sha"] == job.commit_sha


async def test_f3_fails_no_skill(system_factory, deps):
    system = system_factory(cfg=FlowConfig(), intake_deps=deps)
    async with running(system.apps):
        job_id = system.orchestrator.submit(str(FIXTURES / "F3_no_skill"))
        job = await system.orchestrator.wait(job_id, timeout=10)
    assert (job.failure.step, job.failure.code) == (JobState.INTAKE, ErrorCode.NO_SKILL)
    assert "SKILL.md" in job.failure.detail


async def test_f2_waits_for_skill_pick(system_factory, deps):
    system = system_factory(cfg=FlowConfig(), intake_deps=deps)
    async with running(system.apps):
        job_id = system.orchestrator.submit(str(FIXTURES / "F2_multi"))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if system.orchestrator.store.get(job_id).state is JobState.AWAITING_SKILL_PICK:
                break
    job = system.orchestrator.store.get(job_id)
    assert job.state is JobState.AWAITING_SKILL_PICK
    assert len({c["skill_id"] for c in job.candidates}) == 3


async def test_github_url_without_network_is_a_clean_failure(system_factory, deps):
    system = system_factory(cfg=FlowConfig(), intake_deps=deps)
    async with running(system.apps):
        job_id = system.orchestrator.submit("https://gitlab.com/acme/skill")
        job = await system.orchestrator.wait(job_id, timeout=10)
    assert job.failure.code is ErrorCode.BAD_URL
