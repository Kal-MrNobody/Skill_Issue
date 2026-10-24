"""Report agent (stub until step 6). Trust follows the scan gate; lift is never invented."""

from datetime import UTC, datetime

from uagents import Context

from agents.common import StubBehaviour, WorkerApp, envelope, provenance
from contracts.enums import GateDecision, LiftVerdict, TrustVerdict
from contracts.messages import ReportRequest, ReportResult

TRUST_FOR_GATE = {
    GateDecision.BLOCK: TrustVerdict.BLOCKED,
    GateDecision.RESTRICTED: TrustVerdict.WARNINGS,
    GateDecision.STANDARD: TrustVerdict.NOTHING_OBSERVED,
}
SECURITY_ONLY = (
    "Security-only report: static scan done, the skill was not run, "
    "so whether it helps was not measured."
)


async def stub_work(app: WorkerApp, ctx: Context, req: ReportRequest) -> None:
    started = datetime.now(UTC)
    gate = req.scan.gate
    trust = TRUST_FOR_GATE.get(gate, TrustVerdict.WARNINGS)  # unknown gate: fail safe
    lift = LiftVerdict.NOT_APPLICABLE if req.bench is None else LiftVerdict.NO_CLEAR_EFFECT
    text = SECURITY_ONLY if req.bench is None else f"Stub report for {req.repo_url}"
    result = ReportResult(
        **envelope(req),
        report_id=f"rep-{req.job_id}",
        trust=trust,
        lift=lift,
        text=text,
        card={},
        provenance=provenance("report", req.repo_url, req.commit_sha, started),
    )
    await app.send(ctx, result)


def build(seed: str, orchestrator_address: str, behaviour: StubBehaviour | None = None):
    return WorkerApp("report", seed, orchestrator_address, ReportRequest, stub_work, behaviour)
