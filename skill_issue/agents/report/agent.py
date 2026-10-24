"""Report agent (step 1: stub). Real verdicts arrive in step 6."""

from datetime import UTC, datetime

from uagents import Context

from agents.common import StubBehaviour, WorkerApp, envelope, provenance
from contracts.enums import LiftVerdict, TrustVerdict
from contracts.messages import ReportRequest, ReportResult


async def stub_work(app: WorkerApp, ctx: Context, req: ReportRequest) -> None:
    started = datetime.now(UTC)
    lift = LiftVerdict.NOT_APPLICABLE if req.bench is None else LiftVerdict.NO_CLEAR_EFFECT
    result = ReportResult(
        **envelope(req),
        report_id=f"rep-{req.job_id}",
        trust=TrustVerdict.NOTHING_OBSERVED,
        lift=lift,
        text=f"Stub report for {req.repo_url}",
        card={},
        provenance=provenance("report", req.repo_url, req.commit_sha, started),
    )
    await app.send(ctx, result)


def build(seed: str, orchestrator_address: str, behaviour: StubBehaviour | None = None):
    return WorkerApp("report", seed, orchestrator_address, ReportRequest, stub_work, behaviour)
