"""Intake agent (step 1: stub). Real GitHub intake arrives in step 2."""

import hashlib
from datetime import UTC, datetime

from uagents import Context

from agents.common import StubBehaviour, WorkerApp, envelope, provenance
from contracts.messages import IntakeRequest, IntakeResult, SkillCandidate


async def stub_work(app: WorkerApp, ctx: Context, req: IntakeRequest) -> None:
    started = datetime.now(UTC)
    sha = hashlib.sha1(req.repo_url.encode()).hexdigest()  # fake but stable per repo
    n = app.behaviour.skills
    paths = ["SKILL.md"] if n == 1 else [f"skills/s{i}/SKILL.md" for i in range(n)]
    candidates = [
        SkillCandidate(path=p, name=f"stub-{i}", description="stub skill")
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


def build(seed: str, orchestrator_address: str, behaviour: StubBehaviour | None = None):
    return WorkerApp("intake", seed, orchestrator_address, IntakeRequest, stub_work, behaviour)
