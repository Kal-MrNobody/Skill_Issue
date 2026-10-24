"""Orchestrator agent: owns job state. Handlers validate → call core.flow → send."""

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable

from uagents import Agent, Context

from agents.common import emit
from agents.orchestrator.chat import ChatLayer
from agents.runtime import local_agent
from contracts.messages import (
    MESSAGES,
    BenchAccepted,
    BenchResult,
    Failure,
    Heartbeat,
    IntakeResult,
    InternalMessage,
    ReportResult,
    ScanResult,
)
from core.chat import ChatRouter
from core.flow import Effect, Flow, FlowConfig, Ignored, Notify, Send
from core.jobs import InMemoryJobStore, Job, JobStore

RESULT_MODELS = (IntakeResult, ScanResult, BenchAccepted, Heartbeat, BenchResult, ReportResult)
NotifyHook = Callable[[Context, Job, str], Awaitable[None]]


class OrchestratorApp:
    def __init__(
        self,
        seed: str,
        cfg: FlowConfig | None = None,
        tick: float = 1.0,
        store: JobStore | None = None,
        on_notify: NotifyHook | None = None,
        clock: Callable[[], float] = time.monotonic,
        router: ChatRouter | None = None,
        publish_manifest: bool = False,
        agent: Agent | None = None,
    ) -> None:
        self.agent = agent or local_agent("orchestrator", seed)
        self.flow = Flow(cfg or FlowConfig())
        self.store = store or InMemoryJobStore()
        self.workers: dict[str, str] = {}  # role -> address
        self.tasks: set[asyncio.Task] = set()
        self._roles: dict[str, str] = {}  # address -> role
        self._new: deque[str] = deque()
        self._finished: dict[str, asyncio.Event] = {}
        self._on_notify = on_notify
        self._clock = clock
        for model in (*RESULT_MODELS, Failure):
            self.agent.on_message(model=model)(self._on_worker_message)
        self.agent.on_interval(period=tick)(self._on_tick)
        self.chat = None
        if router is not None:  # only the orchestrator speaks the Agent Chat Protocol
            self.chat = ChatLayer(self, router, clock)
            self.agent.include(self.chat.protocol, publish_manifest=publish_manifest)

    def set_workers(self, workers: dict[str, str]) -> None:
        self.workers = dict(workers)
        self._roles = {addr: role for role, addr in workers.items()}

    # --- job entry (chat, or direct for local runs) ------------------------

    def submit(self, repo_url: str, owner: str = "", ref: str | None = None) -> str:
        job = Job(job_id=f"job-{uuid.uuid4().hex[:12]}", repo_url=repo_url, owner=owner, ref=ref)
        self.store.put(job)
        self._finished[job.job_id] = asyncio.Event()
        self._new.append(job.job_id)
        emit("orchestrator", "received", job.job_id, repo_url=repo_url)
        return job.job_id

    def jobs_of(self, owner: str) -> list[Job]:
        return self.store.of_owner(owner)

    async def wait(self, job_id: str, timeout: float) -> Job:
        await asyncio.wait_for(self._finished[job_id].wait(), timeout)
        return self.store.get(job_id)

    # --- handlers ---------------------------------------------------------

    async def _on_worker_message(self, ctx: Context, sender: str, msg: InternalMessage) -> None:
        kind = type(msg).__name__
        role = self._roles.get(sender)
        if role is None:
            emit("orchestrator", "dropped", msg.job_id, reason="unknown sender", kind=kind)
            return
        job = self.store.get(msg.job_id)
        if job is None:
            emit("orchestrator", "dropped", msg.job_id, reason="unknown job", kind=kind)
            return
        emit("orchestrator", "received", job.job_id, kind=kind, from_role=role, attempt=msg.attempt)
        effects = self.flow.on_worker_message(job, role, kind, msg.dict(), self._clock())
        await self._apply(ctx, job, effects)

    async def _on_tick(self, ctx: Context) -> None:
        now = self._clock()
        while self._new:
            job = self.store.get(self._new.popleft())
            await self._apply(ctx, job, self.flow.start(job, now))
        for job in self.store.active():
            await self._apply(ctx, job, self.flow.tick(job, now))

    async def click_run(self, ctx: Context, job: Job) -> None:
        await self._apply(ctx, job, self.flow.click_run(job, self._clock()))

    async def pick_skill(self, ctx: Context, job: Job, skill_path: str) -> None:
        await self._apply(ctx, job, self.flow.pick_skill(job, skill_path, self._clock()))

    # --- effects ----------------------------------------------------------

    async def _apply(self, ctx: Context, job: Job, effects: list[Effect]) -> None:
        self.store.put(job)
        for effect in effects:
            if isinstance(effect, Send):
                await ctx.send(self.workers[effect.role], MESSAGES[effect.kind](**effect.payload))
                emit(
                    "orchestrator",
                    "sent",
                    job.job_id,
                    kind=effect.kind,
                    to=effect.role,
                    attempt=effect.payload["attempt"],
                )
            elif isinstance(effect, Ignored):
                emit("orchestrator", "ignored", job.job_id, reason=effect.reason)
            elif isinstance(effect, Notify):
                fields = {"state": str(job.state)}
                if job.failure:
                    fields |= {"step": str(job.failure.step), "error_code": str(job.failure.code)}
                emit("orchestrator", effect.kind, job.job_id, **fields)
                if self.chat:
                    await self.chat.notify(ctx, job, effect.kind)
                if self._on_notify:
                    await self._on_notify(ctx, job, effect.kind)
                if effect.kind in ("done", "failed"):
                    self._finished.setdefault(job.job_id, asyncio.Event()).set()
