"""Benchmark agent (step 1: stub). Asynchronous: BenchAccepted, Heartbeat..., BenchResult."""

import asyncio
from datetime import UTC, datetime

from uagents import Context

from agents.common import StubBehaviour, WorkerApp, envelope, provenance
from contracts.messages import BenchAccepted, BenchRequest, BenchResult, Heartbeat


async def stub_work(app: WorkerApp, ctx: Context, req: BenchRequest) -> None:
    started = datetime.now(UTC)
    b = app.behaviour
    await app.send(ctx, BenchAccepted(**envelope(req), suite_id=req.suite_id, planned_runs=0))
    elapsed = 0.0
    while elapsed < b.duration:
        step = min(b.heartbeat_every, b.duration - elapsed)
        await asyncio.sleep(step)
        elapsed += step
        if b.heartbeats and elapsed < b.duration:
            await app.send(ctx, Heartbeat(**envelope(req), runs_done=0, runs_total=0))
    result = BenchResult(
        **envelope(req),
        repo_url=req.repo_url,
        commit_sha=req.commit_sha,
        skill_path=req.skill_path,
        suite_id=req.suite_id,
        suite_version="stub",
        model_id="stub",
        k=req.k,
        runs=[],
        provenance=provenance("benchmark", req.repo_url, req.commit_sha, started),
    )
    await app.send(ctx, result)


def build(seed: str, orchestrator_address: str, behaviour: StubBehaviour | None = None):
    return WorkerApp("benchmark", seed, orchestrator_address, BenchRequest, stub_work, behaviour)
