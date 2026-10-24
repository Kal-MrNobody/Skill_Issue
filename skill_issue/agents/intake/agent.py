"""Intake agent: GitHub URL → pinned commit → safe snapshot → skill candidates + claims."""

import asyncio
import hashlib
from datetime import UTC, datetime

from uagents import Context

from agents.common import StubBehaviour, WorkerApp, envelope, provenance
from contracts.messages import SHORT, Claim, IntakeRequest, IntakeResult, SkillCandidate
from core.intake.claims import ClaimRecord
from core.intake.errors import IntakeError
from core.intake.pipeline import IntakeDeps, run_intake
from core.intake.skills import skill_id

MAX_WARNINGS = 50


async def stub_work(app: WorkerApp, ctx: Context, req: IntakeRequest) -> None:
    started = datetime.now(UTC)
    sha = hashlib.sha1(req.repo_url.encode()).hexdigest()  # fake but stable per repo
    n = app.behaviour.skills
    paths = ["SKILL.md"] if n == 1 else [f"skills/s{i}/SKILL.md" for i in range(n)]
    candidates = [
        SkillCandidate(skill_id=skill_id(p), path=p, name=f"stub-{i}", description="stub skill")
        for i, p in enumerate(paths)
    ]
    result = IntakeResult(
        **envelope(req),
        repo_url=req.repo_url,
        commit_sha=sha,
        candidates=candidates,
        provenance=provenance("intake", req.repo_url, sha, started),
    )
    await app.send(ctx, result)


def _claim(c: ClaimRecord) -> Claim:
    return Claim(text=c.text[:SHORT], file=c.file, line=c.line)


def real_work(deps: IntakeDeps):
    async def work(app: WorkerApp, ctx: Context, req: IntakeRequest) -> None:
        started = datetime.now(UTC)
        try:
            out = await asyncio.to_thread(run_intake, req.repo_url, req.ref, deps)
        except IntakeError as ex:
            await app.fail(ctx, req, ex.code, ex.detail[:SHORT], retryable=ex.retryable)
            return
        candidates = [
            SkillCandidate(
                skill_id=c.skill_id,
                path=c.path,
                name=c.name[:100],
                description=c.description[: SHORT * 2],
                files=c.files,
                claims=[_claim(x) for x in c.claims],
            )
            for c in out.candidates
        ]
        result = IntakeResult(
            **envelope(req),
            repo_url=req.repo_url,
            commit_sha=out.commit_sha,
            candidates=candidates,
            claims=[_claim(x) for x in out.claims],
            warnings=[w[:SHORT] for w in out.warnings[:MAX_WARNINGS]],
            provenance=provenance("intake", req.repo_url, out.commit_sha, started),
        )
        await app.send(ctx, result)

    return work


def build(
    seed: str,
    orchestrator_address: str,
    behaviour: StubBehaviour | None = None,
    deps: IntakeDeps | None = None,
):
    """deps=None → stub (step 1 tests); otherwise real intake."""
    work = stub_work if deps is None else real_work(deps)
    return WorkerApp("intake", seed, orchestrator_address, IntakeRequest, work, behaviour)
