"""Chat routing: new jobs, selections (own jobs only), echoes, help, cooldown, job cap."""

import json

from contracts.enums import JobState
from core.chat import (
    COOLDOWN_TEXT,
    RETRY_TEXT,
    STALE_TEXT,
    TOO_MANY_TEXT,
    ChatRouter,
    Drop,
    Say,
    Select,
    StartJob,
)
from core.chat_text import HELP_TEXT
from core.echo import EchoGuard
from core.jobs import Job

A = "user-a"
URL = "https://github.com/acme/skill"


def _job(job_id="job-aaaaaaaaaaaa", state=JobState.AWAITING_RUN_CLICK, n=1):
    job = Job(job_id=job_id, repo_url=URL, owner=A, state=state)
    job.candidates = [
        {"skill_id": f"skl_{i}", "path": f"s{i}/SKILL.md", "name": f"s{i}"} for i in range(n)
    ]
    return job


def _router(**kw):
    return ChatRouter(EchoGuard(**{"cooldown": 30, "max_active_jobs": 2, **kw}))


def test_url_in_free_text_starts_a_job():
    assert _router().route(A, f"can you audit {URL}?", [], 0) == StartJob(URL)


def test_t4_9_no_url_gets_help_with_an_example():
    action = _router().route(A, "hi there", [], 0)
    assert action == Say(action.reply) and action.reply.text == HELP_TEXT
    assert "https://github.com/" in HELP_TEXT


def test_t4_4_duplicate_is_dropped_silently():
    r = _router()
    assert r.route(A, f"audit {URL}", [], 0) == StartJob(URL)
    assert isinstance(r.route(A, f"audit {URL}", [], 1), Drop)


def test_t4_5_own_reply_echoed_back_is_dropped():
    r = _router()
    r.sent(A, "Security scan for s0 (https://github.com/acme/skill): gate STANDARD.", 0)
    echo = "Security scan for s0 (https://github.com/acme/skill): gate STANDARD."
    assert isinstance(r.route(A, echo, [], 1), Drop)


def test_cooldown_and_job_cap_answer_once_without_a_job():
    r = _router()
    assert r.route(A, URL, [], 0) == StartJob(URL)
    assert r.route(A, URL + "/tree/main", [_job()], 5) == _say(COOLDOWN_TEXT)
    busy = [_job("job-1", JobState.SCANNING), _job("job-2", JobState.BENCHMARKING)]
    assert r.route(A, "https://github.com/acme/other", busy, 100) == _say(TOO_MANY_TEXT)


def _say(text):
    from core.cards import Reply

    return Say(Reply(text))


def test_json_run_selection():
    job = _job()
    text = json.dumps({"job_id": job.job_id, "action": "run_benchmark"})
    assert _router().route(A, text, [job], 0) == Select(job.job_id, "run_benchmark")


def test_json_pick_maps_skill_id_to_path():
    job = _job(state=JobState.AWAITING_SKILL_PICK, n=3)
    text = json.dumps({"job_id": job.job_id, "action": "pick_skill", "skill_id": "skl_2"})
    assert _router().route(A, text, [job], 0) == Select(job.job_id, "pick_skill", "s2/SKILL.md")


def test_prose_selection_that_also_repeats_the_url_is_a_selection():
    job = _job()
    text = f"The user wants to run the benchmark for {URL} (job {job.job_id})"
    assert _router().route(A, text, [job], 0) == Select(job.job_id, "run_benchmark")


def test_selection_for_someone_elses_job_is_stale():
    text = json.dumps({"job_id": "job-of-user-b", "action": "run_benchmark"})
    assert _router().route(A, text, [_job()], 0) == _say(STALE_TEXT)


def test_selection_for_a_finished_job_is_stale():
    job = _job(state=JobState.DONE)
    text = json.dumps({"job_id": job.job_id, "action": "run_benchmark"})
    assert _router().route(A, text, [job], 0) == _say(STALE_TEXT)


def test_wrong_action_for_state_is_stale():
    job = _job(state=JobState.AWAITING_SKILL_PICK, n=2)
    text = json.dumps({"job_id": job.job_id, "action": "run_benchmark"})
    assert _router().route(A, text, [job], 0) == _say(STALE_TEXT)


def test_unknown_skill_id_asks_again():
    job = _job(state=JobState.AWAITING_SKILL_PICK, n=2)
    text = json.dumps({"job_id": job.job_id, "action": "pick_skill", "skill_id": "skl_9"})
    assert _router().route(A, text, [job], 0) == _say(RETRY_TEXT)


def test_t4_3_garbage_while_waiting_gets_one_retry_reply():
    assert _router().route(A, "banana", [_job()], 0) == _say(RETRY_TEXT)


def test_fixture_paths_only_in_dev_mode():
    text = "check tests/fixtures/F2_multi"
    assert ChatRouter(dev_mode=False).route(A, text, [], 0) == _say(HELP_TEXT)
    assert ChatRouter(dev_mode=True).route(A, text, [], 0) == StartJob("./tests/fixtures/F2_multi")
