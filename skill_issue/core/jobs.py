"""Job record, job store interface and idempotency keys."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from contracts.enums import ErrorCode, JobState
from core.state_machine import TERMINAL


@dataclass(frozen=True)
class JobFailure:
    step: JobState
    code: ErrorCode
    detail: str = ""


@dataclass
class Job:
    job_id: str
    repo_url: str
    owner: str = ""  # who asked for the job (chat sender); empty for local runs
    ref: str | None = None
    state: JobState = JobState.RECEIVED
    attempt: int = 0  # attempt number of the request for the current step
    deadline: float | None = None  # monotonic seconds; None while waiting on the user
    commit_sha: str | None = None
    skill_path: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    scan: dict[str, Any] | None = None
    bench: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    failure: JobFailure | None = None
    pending: Any = None  # last request sent for the current step (core.flow.Send)
    history: list[JobState] = field(default_factory=lambda: [JobState.RECEIVED])

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL


class JobStore(Protocol):
    def get(self, job_id: str) -> Job | None: ...
    def put(self, job: Job) -> None: ...
    def active(self) -> list[Job]: ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def put(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    def active(self) -> list[Job]:
        return [j for j in self._jobs.values() if not j.terminal]


def idempotency_key(job_id: str, step: JobState, attempt: int) -> str:
    return f"{job_id}:{step}:{attempt}"
