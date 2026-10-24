"""T0.1 round-trip and T0.2 envelope validation for every contract model."""

import inspect
from datetime import UTC, datetime

import pytest
from pydantic.v1 import ValidationError
from uagents import Model

from contracts import messages as m
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

SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = "https://github.com/example/skill"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
ENV = {"job_id": "job-1", "attempt": 1, "schema_version": m.SCHEMA_VERSION}

EXPECTED_MESSAGES = {
    "IntakeRequest",
    "IntakeResult",
    "ScanRequest",
    "ScanResult",
    "BenchRequest",
    "BenchAccepted",
    "Heartbeat",
    "BenchResult",
    "ReportRequest",
    "ReportResult",
    "Failure",
}
RESULTS = {"IntakeResult", "ScanResult", "BenchResult", "ReportResult"}


def _prov(**extra) -> m.Provenance:
    return m.Provenance(
        agent="intake",
        agent_version="0.1.0",
        repo_url=REPO,
        commit_sha=SHA,
        started_at=T0,
        finished_at=T0,
        **extra,
    )


def _scan_result() -> m.ScanResult:
    return m.ScanResult(
        **ENV,
        repo_url=REPO,
        commit_sha=SHA,
        skill_path="SKILL.md",
        findings=[
            m.Finding(
                bucket=Bucket.PROMPT_INJECTION,
                severity=Severity.HIGH,
                rule_id="PI-001",
                message="hidden instruction in HTML comment",
                file="SKILL.md",
                line=7,
            )
        ],
        undeclared_domains=["collector.example.invalid"],
        gate=GateDecision.RESTRICTED,
        provenance=_prov(tool_versions={"cisco-ai-skill-scanner": "1.0.0"}),
    )


def _bench_result() -> m.BenchResult:
    return m.BenchResult(
        **ENV,
        repo_url=REPO,
        commit_sha=SHA,
        skill_path="SKILL.md",
        suite_id="toy",
        suite_version="1",
        model_id="fake-model",
        k=3,
        runs=[
            m.RunRecord(
                task_id="t1",
                condition=Condition.WITH_SKILL,
                repeat=1,
                status=RunStatus.PASSED,
                tokens=1200,
                seconds=3.5,
                skill_used=True,
            )
        ],
        runtime_events=[
            m.RuntimeEvent(
                task_id="t1",
                condition=Condition.WITH_SKILL,
                kind="canary_read",
                severity=Severity.HIGH,
                detail="read ~/.aws/credentials",
            )
        ],
        partial=False,
        provenance=_prov(suite_id="toy", suite_version="1", model_id="fake-model", k=3),
    )


SAMPLES: list[Model] = [
    _prov(),
    m.Claim(text="2x faster reviews", file="README.md", line=3),
    m.SkillCandidate(
        skill_id="skl_0a1b2c3d",
        path="skills/a/SKILL.md",
        name="a",
        description="does a",
        claims=[m.Claim(text="2x faster reviews", file="README.md", line=3)],
    ),
    m.IntakeRequest(**ENV, repo_url=REPO, ref=None),
    m.IntakeResult(
        **ENV,
        repo_url=REPO,
        commit_sha=SHA,
        candidates=[m.SkillCandidate(skill_id="skl_1", path="SKILL.md", name="x", description="y")],
        claims=[m.Claim(text="2x faster reviews", file="README.md", line=3)],
        warnings=["refused symlink: hostname"],
        provenance=_prov(),
    ),
    m.ScanRequest(**ENV, repo_url=REPO, commit_sha=SHA, skill_path="SKILL.md"),
    _scan_result().findings[0],
    _scan_result(),
    m.BenchRequest(
        **ENV,
        repo_url=REPO,
        commit_sha=SHA,
        skill_path="SKILL.md",
        suite_id="toy",
        k=3,
        gate=GateDecision.STANDARD,
    ),
    m.BenchAccepted(**ENV, suite_id="toy", planned_runs=12),
    m.Heartbeat(**ENV, runs_done=4, runs_total=12),
    _bench_result().runs[0],
    _bench_result().runtime_events[0],
    _bench_result(),
    m.ReportRequest(
        **ENV,
        repo_url=REPO,
        commit_sha=SHA,
        skill_path="SKILL.md",
        scan=_scan_result(),
        bench=_bench_result(),
    ),
    m.ReportRequest(
        **ENV, repo_url=REPO, commit_sha=SHA, skill_path="SKILL.md", scan=_scan_result()
    ),
    m.ReportResult(
        **ENV,
        report_id="rep-1",
        trust=TrustVerdict.WARNINGS,
        lift=LiftVerdict.NOT_APPLICABLE,
        text="Trust: warnings. Lift: not applicable.",
        card={"type": "card", "body": []},
        provenance=_prov(),
    ),
    m.Failure(
        **ENV,
        step=JobState.SCANNING,
        error_code=ErrorCode.SCAN_FAILED,
        detail="scanner exited 2",
        retryable=True,
    ),
]


def _contract_models() -> list[type[Model]]:
    return [
        obj
        for _, obj in inspect.getmembers(m, inspect.isclass)
        if issubclass(obj, Model) and obj.__module__ == m.__name__ and obj is not m.InternalMessage
    ]


def _internal_messages() -> list[type[m.InternalMessage]]:
    return [c for c in _contract_models() if issubclass(c, m.InternalMessage)]


def test_every_expected_message_exists_and_is_internal():
    assert {c.__name__ for c in _internal_messages()} == EXPECTED_MESSAGES


def test_every_contract_model_has_a_sample():
    sampled = {type(s) for s in SAMPLES}
    missing = [c.__name__ for c in _contract_models() if c not in sampled]
    assert missing == []


def test_results_carry_required_provenance():
    for name in RESULTS:
        field = getattr(m, name).__fields__["provenance"]
        assert field.required and field.type_ is m.Provenance


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: type(s).__name__)
def test_t0_1_round_trip(sample: Model):
    cls = type(sample)
    parsed = cls.parse_raw(sample.json())
    assert parsed == sample
    assert parsed.json() == sample.json()


@pytest.mark.parametrize("cls", _internal_messages(), ids=lambda c: c.__name__)
@pytest.mark.parametrize("field", ["job_id", "attempt", "schema_version"])
def test_t0_2_envelope_field_required(cls: type[m.InternalMessage], field: str):
    sample = next(s for s in SAMPLES if type(s) is cls)
    data = sample.dict()
    del data[field]
    with pytest.raises(ValidationError):
        cls.parse_obj(data)
    with pytest.raises(ValidationError):
        cls(**data)


@pytest.mark.parametrize(
    "bad",
    [{"job_id": ""}, {"attempt": 0}, {"attempt": -1}, {"schema_version": 0}],
    ids=["empty_job_id", "attempt_zero", "attempt_negative", "schema_zero"],
)
def test_t0_2_envelope_values_validated(bad: dict):
    with pytest.raises(ValidationError):
        m.IntakeRequest(**{**ENV, **bad}, repo_url=REPO)


def test_commit_sha_must_be_full_hex():
    with pytest.raises(ValidationError):
        m.ScanRequest(**ENV, repo_url=REPO, commit_sha="main", skill_path="SKILL.md")


def test_claim_text_is_a_summary_not_file_contents():
    with pytest.raises(ValidationError):
        m.Claim(text="x" * 501, file="README.md", line=1)
