"""Step 1: a fake job flows through five real uAgents in one process (stub workers)."""

import asyncio
import uuid

import pytest
from uagents import Context

from agents.common import StubBehaviour
from agents.runtime import local_agent, running
from contracts.enums import ErrorCode, JobState
from contracts.messages import SCHEMA_VERSION, IntakeRequest, IntakeResult, ScanRequest
from core.flow import FlowConfig

pytestmark = pytest.mark.integration

REPO = "https://github.com/example/skill"
FAST = dict(
    deadlines={
        JobState.INTAKE: 1.0,
        JobState.SCANNING: 1.0,
        JobState.BENCHMARKING: 1.0,
        JobState.REPORTING: 1.0,
    },
    heartbeat_timeout=0.6,
    auto_pick=True,
    auto_run=True,
)


def _cfg(**kw) -> FlowConfig:
    return FlowConfig(**{**FAST, **kw})


async def test_t1_1_happy_path_in_order(system_factory, events):
    system = system_factory(cfg=_cfg())
    async with running(system.apps):
        job_id = system.orchestrator.submit(REPO)
        job = await system.orchestrator.wait(job_id, timeout=10)
    assert job.state is JobState.DONE
    sent = [e["to"] for e in events() if e["event"] == "sent" and e["agent"] == "orchestrator"]
    assert sent == ["intake", "security", "benchmark", "report"]
    assert all(e["job_id"] for e in events() if e["event"] in ("sent", "received"))


@pytest.mark.parametrize(
    "role,step,code",
    [
        ("intake", JobState.INTAKE, ErrorCode.REPO_NOT_FOUND),
        ("security", JobState.SCANNING, ErrorCode.SCAN_FAILED),
        ("benchmark", JobState.BENCHMARKING, ErrorCode.SANDBOX_ERROR),
        ("report", JobState.REPORTING, ErrorCode.INTERNAL),
    ],
)
async def test_t1_2_worker_fail_mode(system_factory, role, step, code):
    system = system_factory(cfg=_cfg(), behaviours={role: StubBehaviour(mode="fail")})
    async with running(system.apps):
        job_id = system.orchestrator.submit(REPO)
        job = await system.orchestrator.wait(job_id, timeout=10)
    assert job.state is JobState.FAILED
    assert (job.failure.step, job.failure.code) == (step, code)


@pytest.mark.parametrize("role", ["intake", "security", "report"])
async def test_t1_2_silent_fast_hop_times_out(system_factory, role):
    system = system_factory(cfg=_cfg(), behaviours={role: StubBehaviour(mode="silent")})
    async with running(system.apps):
        job = await system.orchestrator.wait(system.orchestrator.submit(REPO), timeout=10)
    assert job.failure.code is ErrorCode.TIMEOUT


async def test_t1_3_silent_benchmark_times_out(system_factory):
    system = system_factory(cfg=_cfg(), behaviours={"benchmark": StubBehaviour(mode="silent")})
    async with running(system.apps):
        job = await system.orchestrator.wait(system.orchestrator.submit(REPO), timeout=10)
    assert (job.failure.step, job.failure.code) == (JobState.BENCHMARKING, ErrorCode.TIMEOUT)


async def test_t1_4_duplicate_request_worked_once(system_factory, events):
    system = system_factory(cfg=_cfg())
    intake = system.workers["intake"]
    driver = system.orchestrator.agent  # the address intake trusts
    req = IntakeRequest(job_id="dup-1", attempt=1, schema_version=SCHEMA_VERSION, repo_url=REPO)

    @driver.on_event("startup")
    async def send_twice(ctx: Context):
        await ctx.send(intake.agent.address, req)
        await ctx.send(intake.agent.address, req)

    async with running(system.apps):
        await asyncio.sleep(0.8)
    assert intake.work_count == 1
    dropped = [e for e in events() if e["agent"] == "intake" and e["event"] == "dropped"]
    assert [d["reason"] for d in dropped] == ["DUPLICATE"]


async def test_t1_5_unknown_sender_dropped_and_logged(system_factory, events):
    system = system_factory(cfg=_cfg())
    rogue = local_agent("rogue", f"rogue-{uuid.uuid4().hex}")
    security = system.workers["security"]
    scan = ScanRequest(
        job_id="rogue-1",
        attempt=1,
        schema_version=SCHEMA_VERSION,
        repo_url=REPO,
        commit_sha="b" * 40,
        skill_path="SKILL.md",
    )

    @rogue.on_event("startup")
    async def attack(ctx: Context):
        await ctx.send(security.agent.address, scan)

    class _App:  # running() wants objects with .agent and .tasks
        agent, tasks = rogue, set()

    async with running([*system.apps, _App()]):
        await asyncio.sleep(0.8)
    assert security.work_count == 0
    [drop] = [e for e in events() if e["agent"] == "security" and e["event"] == "dropped"]
    assert drop["reason"] == "ROGUE" and drop["job_id"] == "rogue-1"
    assert drop["sender"] == rogue.address


async def test_t1_5_orchestrator_drops_results_from_unknown_sender(system_factory, events):
    system = system_factory(cfg=_cfg(), behaviours={"intake": StubBehaviour(delay=1.5)})
    rogue = local_agent("rogue", f"rogue-{uuid.uuid4().hex}")
    orch = system.orchestrator
    job_id = orch.submit(REPO)
    forged = IntakeResult(
        job_id=job_id,
        attempt=1,
        schema_version=SCHEMA_VERSION,
        repo_url=REPO,
        commit_sha="c" * 40,
        candidates=[],
        provenance={
            "agent": "rogue",
            "agent_version": "0",
            "repo_url": REPO,
            "commit_sha": "c" * 40,
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:00+00:00",
        },
    )

    @rogue.on_interval(period=0.3)
    async def forge(ctx: Context):
        await ctx.send(orch.agent.address, forged)

    class _App:
        agent, tasks = rogue, set()

    async with running([*system.apps, _App()]):
        await asyncio.sleep(0.8)
        assert orch.store.get(job_id).state is JobState.INTAKE  # forged result had no effect
    drops = [e for e in events() if e["agent"] == "orchestrator" and e["event"] == "dropped"]
    assert drops and all(d["reason"] == "unknown sender" for d in drops)


async def test_t1_6_heartbeats_extend_deadline(system_factory):
    bench = StubBehaviour(duration=1.5, heartbeat_every=0.2)
    system = system_factory(cfg=_cfg(), behaviours={"benchmark": bench})
    async with running(system.apps):
        job = await system.orchestrator.wait(system.orchestrator.submit(REPO), timeout=10)
    assert job.state is JobState.DONE  # took longer than both deadlines, kept alive by heartbeats


async def test_t1_6_no_heartbeats_times_out(system_factory):
    bench = StubBehaviour(duration=1.5, heartbeats=False)
    system = system_factory(cfg=_cfg(), behaviours={"benchmark": bench})
    async with running(system.apps):
        job = await system.orchestrator.wait(system.orchestrator.submit(REPO), timeout=10)
    assert (job.failure.step, job.failure.code) == (JobState.BENCHMARKING, ErrorCode.TIMEOUT)


async def test_t1_7_concurrent_jobs_never_mix(system_factory):
    system = system_factory(
        cfg=_cfg(),
        behaviours={"intake": StubBehaviour(delay=0.3), "security": StubBehaviour(delay=0.2)},
    )
    orch = system.orchestrator
    repos = [f"https://github.com/example/skill-{i}" for i in range(4)]
    async with running(system.apps):
        ids = [orch.submit(r) for r in repos]
        jobs = await asyncio.gather(*(orch.wait(i, timeout=15) for i in ids))
    assert all(j.state is JobState.DONE for j in jobs)
    for repo, job in zip(repos, jobs, strict=True):
        assert job.repo_url == repo
        assert job.scan["repo_url"] == repo and job.bench["repo_url"] == repo
        assert job.report["job_id"] == job.job_id
    assert len({j.commit_sha for j in jobs}) == len(repos)


async def test_orchestrator_handler_never_blocks_on_benchmark(system_factory):
    """While a long benchmark runs, a second job still gets through intake and security."""
    bench = StubBehaviour(duration=2.0, heartbeat_every=0.2)
    system = system_factory(cfg=_cfg(), behaviours={"benchmark": bench})
    orch = system.orchestrator
    async with running(system.apps):
        first = orch.submit(REPO)
        await asyncio.sleep(0.5)
        second = orch.submit("https://github.com/example/other")
        await asyncio.sleep(0.6)
        assert orch.store.get(first).state is JobState.BENCHMARKING
        assert orch.store.get(second).state is JobState.BENCHMARKING
        await orch.wait(first, timeout=10)
