"""Shared enums. Kept free of uagents so core/ can import them (CLAUDE.md rule 3)."""

from enum import StrEnum


class JobState(StrEnum):
    RECEIVED = "RECEIVED"
    INTAKE = "INTAKE"
    AWAITING_SKILL_PICK = "AWAITING_SKILL_PICK"
    SCANNING = "SCANNING"
    AWAITING_RUN_CLICK = "AWAITING_RUN_CLICK"
    BENCHMARKING = "BENCHMARKING"
    REPORTING = "REPORTING"
    DONE = "DONE"
    FAILED = "FAILED"


class JobEvent(StrEnum):
    START = "START"
    ONE_SKILL = "ONE_SKILL"
    MANY_SKILLS = "MANY_SKILLS"
    SKILL_PICKED = "SKILL_PICKED"
    SCAN_PASSED = "SCAN_PASSED"
    SCAN_BLOCKED = "SCAN_BLOCKED"
    NO_SUITE = "NO_SUITE"
    RUN_CLICKED = "RUN_CLICKED"
    BENCH_DONE = "BENCH_DONE"
    REPORT_DONE = "REPORT_DONE"
    FAIL = "FAIL"


class ErrorCode(StrEnum):
    """Why a job ended in FAILED.

    NO_SUITE also appears as a non-failure route (SCANNING → REPORTING, security-only
    report); as an ErrorCode it is only used when a suite was expected and went missing.
    """

    BAD_URL = "BAD_URL"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    PRIVATE_REPO = "PRIVATE_REPO"
    NO_SKILL = "NO_SKILL"
    TOO_LARGE = "TOO_LARGE"
    UNSAFE_ARCHIVE = "UNSAFE_ARCHIVE"
    SCAN_FAILED = "SCAN_FAILED"
    NO_SUITE = "NO_SUITE"
    SANDBOX_ERROR = "SANDBOX_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INTERNAL = "INTERNAL"


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Bucket(StrEnum):
    """The four buckets security findings are sorted into."""

    PROMPT_INJECTION = "PROMPT_INJECTION"
    DANGEROUS_EXECUTION = "DANGEROUS_EXECUTION"
    NETWORK_EGRESS = "NETWORK_EGRESS"
    DATA_ACCESS = "DATA_ACCESS"


class GateDecision(StrEnum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    BLOCK = "BLOCK"


class TrustVerdict(StrEnum):
    BLOCKED = "BLOCKED"
    WARNINGS = "WARNINGS"
    NOTHING_OBSERVED = "NOTHING_OBSERVED"


class LiftVerdict(StrEnum):
    HELPS = "HELPS"
    NO_CLEAR_EFFECT = "NO_CLEAR_EFFECT"
    HURTS = "HURTS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Condition(StrEnum):
    WITH_SKILL = "WITH_SKILL"
    WITHOUT_SKILL = "WITHOUT_SKILL"


class RunStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
