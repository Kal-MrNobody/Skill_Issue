"""Security agent: static scan of the picked skill at the pinned commit → findings + gate."""

import asyncio
from datetime import UTC, datetime

from uagents import Context

from agents.common import StubBehaviour, WorkerApp, emit, envelope, provenance
from contracts.messages import SHORT, Finding, ScanRequest, ScanResult
from core.intake.errors import IntakeError
from core.security.pipeline import ScanDeps, run_scan

MAX_FINDINGS = 200
MAX_DOMAINS = 100


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


def real_work(deps: ScanDeps):
    async def work(app: WorkerApp, ctx: Context, req: ScanRequest) -> None:
        started = datetime.now(UTC)
        try:
            out = await asyncio.to_thread(
                run_scan, req.repo_url, req.commit_sha, req.skill_path, deps
            )
        except IntakeError as ex:
            await app.fail(ctx, req, ex.code, ex.detail[:SHORT], retryable=ex.retryable)
            return
        if out.scan_error:
            emit("security", "scan_failed", req.job_id, detail=out.scan_error_detail)
        findings = [
            Finding(
                bucket=f.bucket,
                severity=f.severity,
                rule_id=f.rule_id,
                message=f.message[:SHORT],
                file=f.file,
                line=f.line,
                source=f.source,
            )
            for f in out.findings[:MAX_FINDINGS]
        ]
        result = ScanResult(
            **envelope(req),
            repo_url=req.repo_url,
            commit_sha=req.commit_sha,
            skill_path=req.skill_path,
            findings=findings,
            domains=out.domains[:MAX_DOMAINS],
            undeclared_domains=out.undeclared_domains[:MAX_DOMAINS],
            gate=out.gate,
            scan_error=out.scan_error,
            provenance=provenance(
                "security",
                req.repo_url,
                req.commit_sha,
                started,
                skill_path=req.skill_path,
                tool_versions={"cisco-ai-skill-scanner": out.scanner_version},
            ),
        )
        await app.send(ctx, result)

    return work


def build(
    seed: str,
    orchestrator_address: str,
    behaviour: StubBehaviour | None = None,
    deps: ScanDeps | None = None,
):
    """deps=None → stub (step 1 tests); otherwise the real scanner."""
    work = stub_work if deps is None else real_work(deps)
    return WorkerApp("security", seed, orchestrator_address, ScanRequest, work, behaviour)
