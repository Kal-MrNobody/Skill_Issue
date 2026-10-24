"""Shared worker plumbing: sender allowlist, duplicate guard, non-blocking work, stub modes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from uagents import Context, Model

from agents.runtime import local_agent
from contracts.enums import ErrorCode, GateDecision, JobState
from contracts.messages import Failure, InternalMessage, Provenance
from core.guards import Decision, RequestGuard
from core.jobs import idempotency_key
from core.logs import log_line

AGENT_VERSION = "0.1.0"
logger = logging.getLogger("skillaudit")


def emit(agent: str, event: str, job_id: str | None = None, **fields: Any) -> None:
    logger.info(log_line(agent, event, job_id, **fields))


def envelope(req: InternalMessage) -> dict[str, Any]:
    return {"job_id": req.job_id, "attempt": req.attempt, "schema_version": req.schema_version}


def provenance(agent: str, repo_url: str, commit_sha: str, started_at: datetime, **extra):
    return Provenance(
        agent=agent,
        agent_version=AGENT_VERSION,
        repo_url=repo_url,
        commit_sha=commit_sha,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        **extra,
    )


@dataclass
class StubBehaviour:
    mode: str = "ok"  # ok | fail | silent
    delay: float = 0.0  # before answering
    duration: float = 0.0  # benchmark: total run time
    heartbeat_every: float = 0.25  # benchmark
    heartbeats: bool = True  # benchmark
    skills: int = 1  # intake: number of candidates
    gate: GateDecision = GateDecision.STANDARD  # security


# step and error code a worker reports when its stub is in fail mode
STUB_FAILURES = {
    "intake": (JobState.INTAKE, ErrorCode.REPO_NOT_FOUND),
    "security": (JobState.SCANNING, ErrorCode.SCAN_FAILED),
    "benchmark": (JobState.BENCHMARKING, ErrorCode.SANDBOX_ERROR),
    "report": (JobState.REPORTING, ErrorCode.INTERNAL),
}

Work = Callable[["WorkerApp", Context, Any], Awaitable[None]]


class WorkerApp:
    """A worker agent. Handlers only validate and spawn; the work runs in a background task."""

    def __init__(
        self,
        role: str,
        seed: str,
        orchestrator_address: str,
        request_model: type[Model],
        work: Work,
        behaviour: StubBehaviour | None = None,
    ) -> None:
        self.role = role
        self.step = STUB_FAILURES[role][0]
        self.orchestrator_address = orchestrator_address
        self.behaviour = behaviour or StubBehaviour()
        self.agent = local_agent(role, seed)
        self.guard = RequestGuard(allowed={orchestrator_address})
        self.tasks: set[asyncio.Task] = set()
        self.work_count = 0
        self._work = work
        self.agent.on_message(model=request_model)(self._on_request)

    async def _on_request(self, ctx: Context, sender: str, msg: InternalMessage) -> None:
        decision = self.guard.check(sender, idempotency_key(msg.job_id, self.step, msg.attempt))
        if decision is not Decision.ACCEPT:
            emit(self.role, "dropped", msg.job_id, reason=str(decision), sender=sender)
            return
        emit(self.role, "received", msg.job_id, kind=type(msg).__name__, attempt=msg.attempt)
        self.work_count += 1
        task = asyncio.get_running_loop().create_task(self._run(ctx, msg))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _run(self, ctx: Context, msg: InternalMessage) -> None:
        b = self.behaviour
        try:
            if b.delay:
                await asyncio.sleep(b.delay)
            if b.mode == "silent":
                emit(self.role, "silent", msg.job_id)
                return
            if b.mode == "fail":
                await self.fail(ctx, msg, STUB_FAILURES[self.role][1], "stub failure")
                return
            await self._work(self, ctx, msg)
        except asyncio.CancelledError:
            raise
        except Exception as ex:  # never leave the orchestrator waiting on a crash
            emit(self.role, "error", msg.job_id, error=type(ex).__name__)
            await self.fail(ctx, msg, ErrorCode.INTERNAL, type(ex).__name__, retryable=True)

    async def send(self, ctx: Context, msg: InternalMessage) -> None:
        await ctx.send(self.orchestrator_address, msg)
        emit(self.role, "sent", msg.job_id, kind=type(msg).__name__, attempt=msg.attempt)

    async def fail(
        self, ctx: Context, req: InternalMessage, code: ErrorCode, detail: str, retryable=False
    ) -> None:
        failure = Failure(
            **envelope(req), step=self.step, error_code=code, detail=detail, retryable=retryable
        )
        await self.send(ctx, failure)
