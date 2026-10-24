"""Every inter-agent message. The only place message models may be defined (CLAUDE.md rule 1).

uagents.Model is a pydantic.v1 BaseModel, so validation here uses the v1 API.
Messages carry references and summaries, never file contents (rule 12).
"""

from datetime import datetime
from typing import Any

from uagents import Field, Model

from contracts.enums import (
    Bucket,
    Condition,
    ErrorCode,
    GateDecision,
    JobState,
    LiftVerdict,
    RunStatus,
    Severity,
    TrustVerdict,
)
from contracts.version import SCHEMA_VERSION  # noqa: F401  (re-exported)

SHA_RE = r"^[0-9a-f]{40}$"
SHORT = 500  # cap for any free-text summary field


class Provenance(Model):
    agent: str
    agent_version: str
    repo_url: str
    commit_sha: str = Field(..., regex=SHA_RE)
    skill_path: str | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)
    suite_id: str | None = None
    suite_version: str | None = None
    model_id: str | None = None
    harness_version: str | None = None
    k: int | None = None
    started_at: datetime
    finished_at: datetime


class InternalMessage(Model):
    """Envelope every agent-to-agent message carries. No defaults on purpose."""

    job_id: str = Field(..., min_length=1, max_length=64)
    attempt: int = Field(..., ge=1)
    schema_version: int = Field(..., ge=1)


# --- intake ---------------------------------------------------------------


class Claim(Model):
    text: str = Field(..., max_length=SHORT)
    file: str
    line: int = Field(..., ge=1)


class SkillCandidate(Model):
    skill_id: str  # stable per SKILL.md path; used in card selections
    path: str
    name: str
    description: str = Field(..., max_length=SHORT * 2)
    files: list[str] = Field(default_factory=list, max_items=200)  # paths only, never contents
    claims: list[Claim] = Field(default_factory=list)


class IntakeRequest(InternalMessage):
    repo_url: str
    ref: str | None = None  # branch or tag; None means the default branch


class IntakeResult(InternalMessage):
    repo_url: str
    commit_sha: str = Field(..., regex=SHA_RE)
    candidates: list[SkillCandidate]
    claims: list[Claim] = Field(default_factory=list)  # every claim found, repo-wide
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance


# --- security -------------------------------------------------------------


class ScanRequest(InternalMessage):
    repo_url: str
    commit_sha: str = Field(..., regex=SHA_RE)
    skill_path: str


class Finding(Model):
    bucket: Bucket
    severity: Severity
    rule_id: str
    message: str = Field(..., max_length=SHORT)
    file: str
    line: int | None = None


class ScanResult(InternalMessage):
    repo_url: str
    commit_sha: str = Field(..., regex=SHA_RE)
    skill_path: str
    findings: list[Finding]
    undeclared_domains: list[str] = Field(default_factory=list)
    gate: GateDecision
    provenance: Provenance


# --- benchmark ------------------------------------------------------------


class BenchRequest(InternalMessage):
    repo_url: str
    commit_sha: str = Field(..., regex=SHA_RE)
    skill_path: str
    suite_id: str
    k: int = Field(..., ge=1)
    gate: GateDecision  # picks the sandbox profile


class BenchAccepted(InternalMessage):
    suite_id: str
    planned_runs: int = Field(..., ge=0)


class Heartbeat(InternalMessage):
    runs_done: int = Field(..., ge=0)
    runs_total: int = Field(..., ge=0)


class RunRecord(Model):
    task_id: str
    condition: Condition
    repeat: int = Field(..., ge=1)
    status: RunStatus
    tokens: int = Field(..., ge=0)
    seconds: float = Field(..., ge=0)
    skill_used: bool


class RuntimeEvent(Model):
    task_id: str
    condition: Condition
    kind: str
    severity: Severity
    detail: str = Field(..., max_length=SHORT)


class BenchResult(InternalMessage):
    repo_url: str
    commit_sha: str = Field(..., regex=SHA_RE)
    skill_path: str
    suite_id: str
    suite_version: str
    model_id: str
    k: int = Field(..., ge=1)
    runs: list[RunRecord]
    runtime_events: list[RuntimeEvent] = Field(default_factory=list)
    partial: bool = False
    provenance: Provenance


# --- report ---------------------------------------------------------------


class ReportRequest(InternalMessage):
    repo_url: str
    commit_sha: str = Field(..., regex=SHA_RE)
    skill_path: str
    scan: ScanResult
    bench: BenchResult | None = None  # None → security-only report


class ReportResult(InternalMessage):
    report_id: str
    trust: TrustVerdict
    lift: LiftVerdict
    text: str  # plain-text fallback sent alongside the card
    card: dict[str, Any]
    provenance: Provenance


# --- any worker -----------------------------------------------------------


class Failure(InternalMessage):
    step: JobState
    error_code: ErrorCode
    detail: str = Field(..., max_length=SHORT)
    retryable: bool = False
    provenance: Provenance | None = None  # absent when no commit was pinned yet


MESSAGES: dict[str, type[InternalMessage]] = {
    cls.__name__: cls
    for cls in (
        IntakeRequest,
        IntakeResult,
        ScanRequest,
        ScanResult,
        BenchRequest,
        BenchAccepted,
        Heartbeat,
        BenchResult,
        ReportRequest,
        ReportResult,
        Failure,
    )
}
