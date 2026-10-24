"""T4.1 card payloads validate (schema, ≤ 64 KB, custom depth ≤ 8); T4.2 selections carry ids."""

import json

import pytest

from contracts.enums import ErrorCode, GateDecision, JobState
from core.cards import (
    MAX_PAYLOAD_BYTES,
    CardError,
    card_metadata,
    iter_selections,
    reply_for,
    validate_card,
)
from core.jobs import Job, JobFailure

SHA = "0123456789abcdef0123456789abcdef01234567"
JOB_ID = "job-0123456789ab"


def _finding(i=0):
    return {
        "bucket": "DANGEROUS_COMMAND",
        "severity": "HIGH",
        "rule_id": f"R{i}",
        "file": "scripts/setup.sh",
        "line": 4 + i,
        "message": "Correlated network to code execution",
        "source": "skill-scanner",
    }


def _job(state=JobState.AWAITING_RUN_CLICK, findings=None, gate=GateDecision.RESTRICTED, n=1):
    cands = [
        {
            "skill_id": f"skl_{i:08x}",
            "path": f"skills/s{i}/SKILL.md",
            "name": f"s{i}",
            "description": "does a thing",
            "files": ["a.py"],
            "claims": [],
        }
        for i in range(n)
    ]
    job = Job(job_id=JOB_ID, repo_url="https://github.com/acme/skill", state=state)
    job.commit_sha, job.skill_path, job.candidates = SHA, cands[0]["path"], cands
    job.scan = {
        "gate": gate,
        "findings": [_finding()] if findings is None else findings,
        "domains": ["api.example.invalid"],
        "undeclared_domains": ["api.example.invalid"],
        "scan_error": None,
        "provenance": {"tool_versions": {"cisco-ai-skill-scanner": "2.2.2"}},
    }
    return job


def _done(job, bench=True):
    job.state = JobState.DONE
    lift = "NO_CLEAR_EFFECT" if bench else "NOT_APPLICABLE"
    job.report = {"report_id": "rep-1", "trust": "WARNINGS", "lift": lift, "text": "t", "card": {}}
    return job


def _failed():
    job = _job(JobState.FAILED)
    job.failure = JobFailure(JobState.INTAKE, ErrorCode.NO_SKILL, "No SKILL.md found")
    return job


REPLIES = {
    "picker": reply_for(_job(JobState.AWAITING_SKILL_PICK, n=3), "pick_skill"),
    "security": reply_for(_job(), "run_benchmark"),
    "report": reply_for(_done(_job()), "done"),
    "blocked": reply_for(_done(_job(gate=GateDecision.BLOCK), bench=False), "done"),
    "failed": reply_for(_failed(), "failed"),
}
CARDS = [k for k, r in REPLIES.items() if r.card_kind]


@pytest.mark.parametrize("name", CARDS)
def test_t4_1_payload_validates_and_fits(name):
    reply = REPLIES[name]
    validate_card(reply.card_kind, reply.payload)
    assert len(json.dumps(reply.payload).encode()) <= MAX_PAYLOAD_BYTES


@pytest.mark.parametrize("name", list(REPLIES))
def test_every_reply_has_useful_text(name):
    assert len(REPLIES[name].text) > 20


@pytest.mark.parametrize("name", CARDS)
def test_t4_2_every_selection_has_job_id_and_action(name):
    reply = REPLIES[name]
    for sel in iter_selections(reply.card_kind, reply.payload):
        assert sel["job_id"] == JOB_ID and sel["action"]


def test_picker_is_a_carousel_with_one_item_per_skill():
    r = REPLIES["picker"]
    assert r.card_kind == "carousel" and len(r.payload["items"]) == 3
    sels = list(iter_selections(r.card_kind, r.payload))
    assert {s["action"] for s in sels} == {"pick_skill"}
    assert [s["skill_id"] for s in sels] == ["skl_00000000", "skl_00000001", "skl_00000002"]


def test_security_card_has_run_button_with_estimate():
    r = REPLIES["security"]
    assert r.card_kind == "detail"
    [cta] = r.payload["ctas"]
    assert cta["selection"]["action"] == "run_benchmark" and "min" in cta["label"]
    rows = {row["label"]: row["value"] for row in r.payload["summary_rows"]}
    assert rows["Gate"] == "RESTRICTED" and "scripts/setup.sh:4" in json.dumps(r.payload)


def test_t4_7_blocked_report_has_no_buttons_and_is_terminal():
    r = REPLIES["blocked"]
    assert list(iter_selections(r.card_kind, r.payload)) == []
    assert "Run benchmark" not in json.dumps(r.payload)
    assert r.terminal is True


def test_failure_reply_is_text_only_and_explains():
    r = REPLIES["failed"]
    assert r.card_kind is None and "SKILL.md" in r.text


def test_many_findings_still_fit_in_64kb():
    many = [_finding(i) for i in range(5000)]
    for reply in (
        reply_for(_done(_job(findings=many)), "done"),
        reply_for(_job(findings=many), "run_benchmark"),
    ):
        validate_card(reply.card_kind, reply.payload)
        assert len(json.dumps(reply.payload).encode()) <= MAX_PAYLOAD_BYTES


def test_no_letter_grades_or_scores_in_cards():
    blob = json.dumps({k: (r.text, r.payload) for k, r in REPLIES.items()}).lower()
    for banned in ("grade", "score", '"a+"', "/10", "/100"):
        assert banned not in blob


def test_card_metadata_is_all_strings():
    r = REPLIES["security"]
    meta = card_metadata(r)
    assert all(isinstance(v, str) for v in meta.values())
    assert meta["card_protocol_version"] == "1" and meta["requires_card_interaction"] == "true"
    assert json.loads(meta["card_payload"]) == r.payload


def test_terminal_flag_only_on_terminal_cards():
    assert "is_terminal" not in card_metadata(REPLIES["security"])
    assert card_metadata(REPLIES["report"])["is_terminal"] == "true"


def _deep(n):
    node = {"type": "text", "value": "leaf"}
    for _ in range(n - 1):
        node = {"type": "group", "direction": "column", "children": [node]}
    return {"root": node}


def test_custom_depth_limit():
    validate_card("custom", _deep(8))
    with pytest.raises(CardError):
        validate_card("custom", _deep(9))


ITEM = {"id": "1", "title": "t", "primary_cta": {"label": "a", "selection": {}}}


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("nope", {"title": "x"}),
        ("carousel", {"title": "x", "items": []}),
        ("carousel", {"title": "x", "items": [{"id": "1", "title": "t"}]}),
        ("detail", {"title": "x", "ctas": [{"label": "go"}]}),
        ("detail", {"summary_rows": []}),
        ("custom", {"data": {"root": {"type": "text", "value": "x"}}}),
        ("custom", {"root": {"type": "marquee"}}),
        ("custom", {"root": {"type": "badge", "label": "x", "variant": "danger"}}),
        ("carousel", {"title": "x" * 70_000, "items": [ITEM]}),
    ],
)
def test_validator_rejects_bad_payloads(kind, payload):
    with pytest.raises(CardError):
        validate_card(kind, payload)
