"""Orchestrator flow engine (pure): states, sends, deadlines, retries, stale results."""

import pytest

from contracts.enums import ErrorCode, GateDecision, JobState
from contracts.version import SCHEMA_VERSION
from core.flow import Flow, FlowConfig, Ignored, Notify, Send
from core.jobs import Job

S = JobState
SHA = "a" * 40
REPO = "https://github.com/example/skill"


def _cfg(**kw) -> FlowConfig:
    base = dict(
        deadlines={S.INTAKE: 5, S.SCANNING: 5, S.BENCHMARKING: 5, S.REPORTING: 5},
        heartbeat_timeout=3,
        max_attempts=2,
        auto_pick=False,
        auto_run=False,
        suite_id="toy",
        k=3,
    )
    base.update(kw)
    return FlowConfig(**base)


def _env(job: Job) -> dict:
    return {"job_id": job.job_id, "attempt": job.attempt, "schema_version": SCHEMA_VERSION}


def _intake(job, n=1):
    cands = [{"path": f"s{i}/SKILL.md", "name": f"s{i}", "description": "d"} for i in range(n)]
    return {**_env(job), "repo_url": REPO, "commit_sha": SHA, "candidates": cands}


def _scan(job, gate=GateDecision.STANDARD):
    return {
        **_env(job),
        "repo_url": REPO,
        "commit_sha": SHA,
        "skill_path": "s0/SKILL.md",
        "findings": [],
        "gate": gate,
    }


def _sends(effects) -> list[Send]:
    return [e for e in effects if isinstance(e, Send)]


@pytest.fixture
def flow():
    return Flow(_cfg())


@pytest.fixture
def job():
    return Job(job_id="j1", repo_url=REPO)


def test_start_sends_intake_request_with_envelope(flow, job):
    effects = flow.start(job, now=0)
    assert job.state is S.INTAKE and job.attempt == 1 and job.deadline == 5
    [send] = _sends(effects)
    assert send.role == "intake" and send.kind == "IntakeRequest"
    assert send.payload == {
        "job_id": "j1",
        "attempt": 1,
        "schema_version": SCHEMA_VERSION,
        "repo_url": REPO,
        "ref": None,
    }


def test_full_happy_path_with_clicks(flow, job):
    flow.start(job, 0)
    [send] = _sends(flow.on_worker_message(job, "intake", "IntakeResult", _intake(job), 1))
    assert job.state is S.SCANNING and send.kind == "ScanRequest"
    assert send.payload["commit_sha"] == SHA and send.payload["skill_path"] == "s0/SKILL.md"

    effects = flow.on_worker_message(job, "security", "ScanResult", _scan(job), 2)
    assert job.state is S.AWAITING_RUN_CLICK and job.deadline is None
    assert Notify("j1", "run_benchmark") in effects and not _sends(effects)

    [send] = _sends(flow.click_run(job, 3))
    assert job.state is S.BENCHMARKING and send.kind == "BenchRequest"
    assert send.payload["suite_id"] == "toy" and send.payload["k"] == 3

    flow.on_worker_message(
        job, "benchmark", "BenchAccepted", {**_env(job), "suite_id": "toy", "planned_runs": 18}, 4
    )
    bench = {
        **_env(job),
        "repo_url": REPO,
        "commit_sha": SHA,
        "skill_path": "s0/SKILL.md",
        "suite_id": "toy",
        "suite_version": "1",
        "model_id": "m",
        "k": 3,
        "runs": [],
    }
    [send] = _sends(flow.on_worker_message(job, "benchmark", "BenchResult", bench, 5))
    assert job.state is S.REPORTING and send.kind == "ReportRequest"
    assert send.payload["scan"]["gate"] == GateDecision.STANDARD
    assert send.payload["bench"]["suite_id"] == "toy"

    report = {
        **_env(job),
        "report_id": "r1",
        "trust": "NOTHING_OBSERVED",
        "lift": "NOT_APPLICABLE",
        "text": "t",
        "card": {},
    }
    effects = flow.on_worker_message(job, "report", "ReportResult", report, 6)
    assert job.state is S.DONE and Notify("j1", "done") in effects
    assert job.history == [
        S.RECEIVED,
        S.INTAKE,
        S.SCANNING,
        S.AWAITING_RUN_CLICK,
        S.BENCHMARKING,
        S.REPORTING,
        S.DONE,
    ]


def test_auto_run_clicks_immediately(job):
    flow = Flow(_cfg(auto_run=True))
    flow.start(job, 0)
    flow.on_worker_message(job, "intake", "IntakeResult", _intake(job), 1)
    [send] = _sends(flow.on_worker_message(job, "security", "ScanResult", _scan(job), 2))
    assert job.state is S.BENCHMARKING and send.kind == "BenchRequest"


def test_many_skills_waits_for_pick(flow, job):
    flow.start(job, 0)
    effects = flow.on_worker_message(job, "intake", "IntakeResult", _intake(job, 3), 1)
    assert job.state is S.AWAITING_SKILL_PICK and Notify("j1", "pick_skill") in effects
    assert isinstance(flow.pick_skill(job, "nope/SKILL.md", 2)[0], Ignored)
    [send] = _sends(flow.pick_skill(job, "s2/SKILL.md", 2))
    assert job.state is S.SCANNING and send.payload["skill_path"] == "s2/SKILL.md"


def test_auto_pick_takes_first_skill(job):
    flow = Flow(_cfg(auto_pick=True))
    flow.start(job, 0)
    [send] = _sends(flow.on_worker_message(job, "intake", "IntakeResult", _intake(job, 3), 1))
    assert send.payload["skill_path"] == "s0/SKILL.md"


def test_zero_candidates_fails_no_skill(flow, job):
    flow.start(job, 0)
    flow.on_worker_message(job, "intake", "IntakeResult", _intake(job, 0), 1)
    assert job.state is S.FAILED and job.failure.code is ErrorCode.NO_SKILL
    assert job.failure.step is S.INTAKE


@pytest.mark.parametrize("gate,suite", [(GateDecision.BLOCK, "toy"), (GateDecision.STANDARD, None)])
def test_block_or_no_suite_goes_straight_to_report(job, gate, suite):
    flow = Flow(_cfg(suite_id=suite, auto_run=True))
    flow.start(job, 0)
    flow.on_worker_message(job, "intake", "IntakeResult", _intake(job), 1)
    [send] = _sends(flow.on_worker_message(job, "security", "ScanResult", _scan(job, gate), 2))
    assert job.state is S.REPORTING and send.kind == "ReportRequest"
    assert send.payload["bench"] is None


def test_deadline_timeout_fails_with_step(flow, job):
    flow.start(job, 0)
    assert flow.tick(job, 4.9) == []
    effects = flow.tick(job, 5)
    assert job.state is S.FAILED and Notify("j1", "failed") in effects
    assert (job.failure.step, job.failure.code) == (S.INTAKE, ErrorCode.TIMEOUT)


def test_tick_never_times_out_user_waits(flow, job):
    flow.start(job, 0)
    flow.on_worker_message(job, "intake", "IntakeResult", _intake(job), 1)
    flow.on_worker_message(job, "security", "ScanResult", _scan(job), 2)
    assert flow.tick(job, 10_000) == [] and job.state is S.AWAITING_RUN_CLICK


def test_heartbeat_extends_benchmark_deadline(job):
    flow = Flow(_cfg(auto_run=True))
    flow.start(job, 0)
    flow.on_worker_message(job, "intake", "IntakeResult", _intake(job), 1)
    flow.on_worker_message(job, "security", "ScanResult", _scan(job), 2)
    assert job.deadline == 2 + 5
    flow.on_worker_message(
        job, "benchmark", "Heartbeat", {**_env(job), "runs_done": 1, "runs_total": 9}, 6
    )
    assert job.deadline == 6 + 3
    assert flow.tick(job, 8.9) == [] and job.state is S.BENCHMARKING
    flow.tick(job, 9)
    assert (job.failure.step, job.failure.code) == (S.BENCHMARKING, ErrorCode.TIMEOUT)


def test_stale_attempt_ignored(flow, job):
    flow.start(job, 0)
    data = _intake(job)
    data["attempt"] = 7
    [effect] = flow.on_worker_message(job, "intake", "IntakeResult", data, 1)
    assert isinstance(effect, Ignored) and "stale" in effect.reason
    assert job.state is S.INTAKE


def test_wrong_role_or_kind_ignored(flow, job):
    flow.start(job, 0)
    [e1] = flow.on_worker_message(job, "security", "IntakeResult", _intake(job), 1)
    [e2] = flow.on_worker_message(job, "intake", "ScanResult", _scan(job), 1)
    assert isinstance(e1, Ignored) and isinstance(e2, Ignored)
    assert job.state is S.INTAKE


def test_results_after_terminal_ignored(flow, job):
    flow.start(job, 0)
    flow.tick(job, 100)
    [effect] = flow.on_worker_message(job, "intake", "IntakeResult", _intake(job), 101)
    assert isinstance(effect, Ignored) and job.state is S.FAILED


def _failure(job, step, code=ErrorCode.SCAN_FAILED, retryable=False):
    return {**_env(job), "step": step, "error_code": code, "detail": "x", "retryable": retryable}


def test_failure_fails_job_with_reported_code(flow, job):
    flow.start(job, 0)
    flow.on_worker_message(
        job, "intake", "Failure", _failure(job, S.INTAKE, ErrorCode.REPO_NOT_FOUND), 1
    )
    assert (job.failure.step, job.failure.code) == (S.INTAKE, ErrorCode.REPO_NOT_FOUND)


def test_retryable_failure_resends_with_next_attempt_then_gives_up(flow, job):
    flow.start(job, 0)
    [send] = _sends(
        flow.on_worker_message(job, "intake", "Failure", _failure(job, S.INTAKE, retryable=True), 1)
    )
    assert send.payload["attempt"] == 2 and job.attempt == 2 and job.deadline == 6
    flow.on_worker_message(job, "intake", "Failure", _failure(job, S.INTAKE, retryable=True), 2)
    assert job.state is S.FAILED and job.failure.code is ErrorCode.SCAN_FAILED


def test_failure_for_another_step_ignored(flow, job):
    flow.start(job, 0)
    [effect] = flow.on_worker_message(job, "intake", "Failure", _failure(job, S.SCANNING), 1)
    assert isinstance(effect, Ignored) and job.state is S.INTAKE


def test_click_in_wrong_state_ignored(flow, job):
    flow.start(job, 0)
    [effect] = flow.click_run(job, 1)
    assert isinstance(effect, Ignored) and job.state is S.INTAKE
