"""Orchestrator flow engine.

Pure: no network, no uagents. Messages arrive and leave as (kind, payload dict); the agent
layer turns them into contract models. Each call mutates the given Job and returns effects.
"""

from dataclasses import dataclass, field
from typing import Any

from contracts.enums import ErrorCode, GateDecision, JobEvent, JobState
from contracts.version import SCHEMA_VERSION
from core.jobs import Job, JobFailure
from core.state_machine import transition

S, E = JobState, JobEvent

ROLE_FOR_STATE = {
    S.INTAKE: "intake",
    S.SCANNING: "security",
    S.BENCHMARKING: "benchmark",
    S.REPORTING: "report",
}
RESULT_KINDS = {
    S.INTAKE: {"IntakeResult"},
    S.SCANNING: {"ScanResult"},
    S.BENCHMARKING: {"BenchAccepted", "Heartbeat", "BenchResult"},
    S.REPORTING: {"ReportResult"},
}


@dataclass(frozen=True)
class Send:
    role: str
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class Notify:
    """Something the user should hear about: pick_skill | run_benchmark | done | failed."""

    job_id: str
    kind: str


@dataclass(frozen=True)
class Ignored:
    job_id: str
    reason: str


Effect = Send | Notify | Ignored


@dataclass
class FlowConfig:
    deadlines: dict[JobState, float] = field(
        default_factory=lambda: {S.INTAKE: 60, S.SCANNING: 180, S.BENCHMARKING: 60, S.REPORTING: 60}
    )
    heartbeat_timeout: float = 60  # each BenchAccepted/Heartbeat pushes the deadline this far
    max_attempts: int = 2
    auto_pick: bool = False  # step 1 only: pick the first skill without asking
    auto_run: bool = False  # step 1 only: simulate the "Run benchmark" click
    suite_id: str | None = "toy"  # None → no matching suite → security-only report
    k: int = 3


class Flow:
    def __init__(self, cfg: FlowConfig) -> None:
        self.cfg = cfg

    # --- entry points -----------------------------------------------------

    def start(self, job: Job, now: float) -> list[Effect]:
        self._move(job, E.START)
        return self._request(job, "IntakeRequest", {"repo_url": job.repo_url, "ref": job.ref}, now)

    def on_worker_message(
        self, job: Job, role: str, kind: str, data: dict[str, Any], now: float
    ) -> list[Effect]:
        if job.terminal:
            return [Ignored(job.job_id, f"{kind} after terminal state {job.state}")]
        if ROLE_FOR_STATE.get(job.state) != role:
            return [Ignored(job.job_id, f"{kind} from {role} while {job.state}")]
        if data.get("attempt") != job.attempt:
            return [Ignored(job.job_id, f"stale attempt {data.get('attempt')} != {job.attempt}")]
        if kind == "Failure":
            return self._on_failure(job, data, now)
        if kind not in RESULT_KINDS[job.state]:
            return [Ignored(job.job_id, f"{kind} not expected while {job.state}")]
        return getattr(self, f"_on_{kind}")(job, data, now)

    def pick_skill(self, job: Job, skill_path: str, now: float) -> list[Effect]:
        if job.state is not S.AWAITING_SKILL_PICK:
            return [Ignored(job.job_id, f"skill pick while {job.state}")]
        if skill_path not in {c["path"] for c in job.candidates}:
            return [Ignored(job.job_id, f"unknown skill {skill_path!r}")]
        self._move(job, E.SKILL_PICKED)
        job.skill_path = skill_path
        return self._scan(job, now)

    def click_run(self, job: Job, now: float) -> list[Effect]:
        if job.state is not S.AWAITING_RUN_CLICK:
            return [Ignored(job.job_id, f"run click while {job.state}")]
        self._move(job, E.RUN_CLICKED)
        fields = {
            **self._refs(job),
            "suite_id": self.cfg.suite_id,
            "k": self.cfg.k,
            "gate": job.scan["gate"],
        }
        return self._request(job, "BenchRequest", fields, now)

    def tick(self, job: Job, now: float) -> list[Effect]:
        if job.state in ROLE_FOR_STATE and job.deadline is not None and now >= job.deadline:
            return self._fail(job, ErrorCode.TIMEOUT, f"no answer from {job.pending.role}")
        return []

    # --- results ----------------------------------------------------------

    def _on_IntakeResult(self, job: Job, data: dict, now: float) -> list[Effect]:  # noqa: N802
        job.commit_sha = data["commit_sha"]
        job.candidates = list(data["candidates"])
        if not job.candidates:
            return self._fail(job, ErrorCode.NO_SKILL, "no SKILL.md found")
        if len(job.candidates) == 1:
            self._move(job, E.ONE_SKILL)
            job.skill_path = job.candidates[0]["path"]
            return self._scan(job, now)
        self._move(job, E.MANY_SKILLS)
        job.deadline = None
        if self.cfg.auto_pick:
            return self.pick_skill(job, job.candidates[0]["path"], now)
        return [Notify(job.job_id, "pick_skill")]

    def _on_ScanResult(self, job: Job, data: dict, now: float) -> list[Effect]:  # noqa: N802
        job.scan = data
        if data["gate"] == GateDecision.BLOCK:
            self._move(job, E.SCAN_BLOCKED)
            return self._report(job, now)
        if self.cfg.suite_id is None:
            self._move(job, E.NO_SUITE)
            return self._report(job, now)
        self._move(job, E.SCAN_PASSED)
        job.deadline = None
        if self.cfg.auto_run:
            return self.click_run(job, now)
        return [Notify(job.job_id, "run_benchmark")]

    def _on_BenchAccepted(self, job: Job, data: dict, now: float) -> list[Effect]:  # noqa: N802
        job.deadline = now + self.cfg.heartbeat_timeout
        return []

    _on_Heartbeat = _on_BenchAccepted

    def _on_BenchResult(self, job: Job, data: dict, now: float) -> list[Effect]:  # noqa: N802
        job.bench = data
        self._move(job, E.BENCH_DONE)
        return self._report(job, now)

    def _on_ReportResult(self, job: Job, data: dict, now: float) -> list[Effect]:  # noqa: N802
        job.report = data
        self._move(job, E.REPORT_DONE)
        job.deadline = None
        return [Notify(job.job_id, "done")]

    def _on_failure(self, job: Job, data: dict, now: float) -> list[Effect]:
        if data["step"] != job.state:
            return [Ignored(job.job_id, f"Failure for {data['step']} while {job.state}")]
        if data.get("retryable") and job.attempt < self.cfg.max_attempts:
            job.attempt += 1
            return self._send(job, job.pending.kind, job.pending.payload, now)
        return self._fail(job, ErrorCode(data["error_code"]), data.get("detail", ""))

    # --- helpers ----------------------------------------------------------

    def _refs(self, job: Job) -> dict[str, Any]:
        return {
            "repo_url": job.repo_url,
            "commit_sha": job.commit_sha,
            "skill_path": job.skill_path,
        }

    def _scan(self, job: Job, now: float) -> list[Effect]:
        return self._request(job, "ScanRequest", self._refs(job), now)

    def _report(self, job: Job, now: float) -> list[Effect]:
        fields = {**self._refs(job), "scan": job.scan, "bench": job.bench}
        return self._request(job, "ReportRequest", fields, now)

    def _request(self, job: Job, kind: str, fields: dict[str, Any], now: float) -> list[Effect]:
        job.attempt = 1
        return self._send(job, kind, fields, now)

    def _send(self, job: Job, kind: str, fields: dict[str, Any], now: float) -> list[Effect]:
        envelope = {"job_id": job.job_id, "attempt": job.attempt, "schema_version": SCHEMA_VERSION}
        send = Send(ROLE_FOR_STATE[job.state], kind, {**fields, **envelope})
        job.pending = send
        job.deadline = now + self.cfg.deadlines[job.state]
        return [send]

    def _fail(self, job: Job, code: ErrorCode, detail: str) -> list[Effect]:
        job.failure = JobFailure(job.state, code, detail)
        self._move(job, E.FAIL)
        job.deadline = None
        return [Notify(job.job_id, "failed")]

    def _move(self, job: Job, event: JobEvent) -> None:
        job.state = transition(job.state, event)
        job.history.append(job.state)
