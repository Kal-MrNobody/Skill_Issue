"""Security agent (step 1: stub). The real scanner wrapper arrives in step 3."""

from datetime import UTC, datetime

from uagents import Context

from agents.common import StubBehaviour, WorkerApp, envelope, provenance
from contracts.messages import ScanRequest, ScanResult


async def stub_work(app: WorkerApp, ctx: Context, req: ScanRequest) -> None:
    started = datetime.now(UTC)
    result = ScanResult(
        **envelope(req),
        repo_url=req.repo_url,
        commit_sha=req.commit_sha,
        skill_path=req.skill_path,
        findings=[],
        gate=app.behaviour.gate,
        provenance=provenance("security", req.repo_url, req.commit_sha, started),
    )
    await app.send(ctx, result)


def build(seed: str, orchestrator_address: str, behaviour: StubBehaviour | None = None):
    return WorkerApp("security", seed, orchestrator_address, ScanRequest, stub_work, behaviour)
