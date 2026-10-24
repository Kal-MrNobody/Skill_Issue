"""T4.3 selection parsing: JSON first, planner prose second, garbage → None."""

import json

import pytest

from contracts.enums import JobState
from core.selection import JobView, Selection, parse_selection

PICK = JobView("j_8f3", JobState.AWAITING_SKILL_PICK, ("skl_1", "skl_2", "skl_3"))
RUN = JobView("job-0123456789ab", JobState.AWAITING_RUN_CLICK, ())


def test_json_pick():
    text = json.dumps({"job_id": "j_8f3", "action": "pick_skill", "skill_id": "skl_2"})
    assert parse_selection(text, [PICK]) == Selection("j_8f3", "pick_skill", "skl_2")


def test_json_run():
    text = json.dumps({"job_id": RUN.job_id, "action": "run_benchmark"})
    assert parse_selection(text, [RUN]) == Selection(RUN.job_id, "run_benchmark", None)


def test_json_for_unknown_job_is_still_parsed_and_left_to_the_caller():
    text = json.dumps({"job_id": "job-gone", "action": "run_benchmark"})
    assert parse_selection(text, [RUN]) == Selection("job-gone", "run_benchmark", None)


def test_t4_3_plan_prose_example():
    text = "The user picked skill skl_2 for job j_8f3 and wants to run the benchmark"
    assert parse_selection(text, [PICK, RUN]) == Selection("j_8f3", "pick_skill", "skl_2")


@pytest.mark.parametrize(
    "text",
    [
        "The user wants to run the benchmark for job job-0123456789ab.",
        "User clicked Run benchmark (job job-0123456789ab, action run_benchmark)",
        "run_benchmark job-0123456789ab",
    ],
)
def test_prose_run(text):
    assert parse_selection(text, [PICK, RUN]) == Selection(RUN.job_id, "run_benchmark", None)


def test_prose_without_job_id_uses_the_only_waiting_job():
    text = "The user selected skl_3"
    assert parse_selection(text, [PICK]) == Selection("j_8f3", "pick_skill", "skl_3")


def test_prose_ambiguous_without_job_id_is_none():
    assert parse_selection("run the benchmark please", [PICK, RUN]) is None


@pytest.mark.parametrize(
    "text",
    ["", "hello", "{not json", json.dumps(["a"]), json.dumps({"action": "x"}), "skl_9 for job zz"],
)
def test_t4_3_garbage_is_none(text):
    assert parse_selection(text, [PICK, RUN]) is None


def test_prose_pick_needs_a_known_skill_id():
    assert parse_selection("The user picked skill skl_99 for job j_8f3", [PICK]) is None
