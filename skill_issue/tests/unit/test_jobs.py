"""Job store, idempotency keys, sender/duplicate guards, structured log lines."""

import json

from contracts.enums import JobState
from core.guards import Decision, RequestGuard
from core.jobs import InMemoryJobStore, Job, idempotency_key
from core.logs import log_line


def test_store_put_get_and_isolation():
    store = InMemoryJobStore()
    a, b = Job(job_id="a", repo_url="r1"), Job(job_id="b", repo_url="r2")
    store.put(a)
    store.put(b)
    assert store.get("a") is a and store.get("b") is b and store.get("zzz") is None
    a.state = JobState.INTAKE
    assert store.get("b").state is JobState.RECEIVED
    assert {j.job_id for j in store.active()} == {"a", "b"}


def test_active_excludes_terminal():
    store = InMemoryJobStore()
    done = Job(job_id="d", repo_url="r", state=JobState.DONE)
    store.put(done)
    assert store.active() == []


def test_idempotency_key():
    assert idempotency_key("j1", JobState.INTAKE, 1) == "j1:INTAKE:1"
    assert idempotency_key("j1", JobState.INTAKE, 2) != idempotency_key("j1", JobState.INTAKE, 1)


def test_guard_allows_only_orchestrator_and_drops_duplicates():
    guard = RequestGuard(allowed={"orch"})
    assert guard.check("rogue", "k1") is Decision.ROGUE
    assert guard.check("orch", "k1") is Decision.ACCEPT
    assert guard.check("orch", "k1") is Decision.DUPLICATE
    assert guard.check("orch", "k2") is Decision.ACCEPT


def test_guard_memory_is_bounded():
    guard = RequestGuard(allowed={"o"}, max_keys=2)
    for k in ("a", "b", "c"):
        guard.check("o", k)
    assert guard.check("o", "a") is Decision.ACCEPT  # evicted, so accepted again


def test_log_line_is_json_with_agent_and_job():
    line = json.loads(log_line("intake", "sent", job_id="j1", kind="IntakeResult"))
    assert line == {"agent": "intake", "event": "sent", "job_id": "j1", "kind": "IntakeResult"}
    assert json.loads(log_line("security", "dropped"))["job_id"] is None
