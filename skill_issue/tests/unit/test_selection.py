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


PICK_NAMED = JobView(
    "job-old", JobState.AWAITING_SKILL_PICK, ("skl_a", "skl_b"), ("pdf", "docx-writer")
)
PICK_NAMED_NEW = JobView(
    "job-new", JobState.AWAITING_SKILL_PICK, ("skl_a", "skl_b"), ("pdf", "docx-writer")
)


def test_prose_skill_name_picks_it():
    assert parse_selection("audit docx-writer please", [PICK_NAMED]) == Selection(
        "job-old", "pick_skill", "skl_b"
    )


def test_bare_skill_name_or_id_matches_case_insensitively():
    assert parse_selection("PDF", [PICK_NAMED]) == Selection("job-old", "pick_skill", "skl_a")
    assert parse_selection("skl_b", [PICK_NAMED]) == Selection("job-old", "pick_skill", "skl_b")


def test_without_job_id_the_newest_waiting_job_with_that_skill_wins():
    waiting = [PICK_NAMED, PICK_NAMED_NEW, RUN]
    assert parse_selection("pdf", waiting) == Selection("job-new", "pick_skill", "skl_a")


def test_name_inside_a_longer_word_does_not_match():
    assert parse_selection("pdfs are great", [PICK_NAMED]) is None


def test_two_different_skills_named_is_ambiguous():
    assert parse_selection("pdf or docx-writer?", [PICK_NAMED]) is None
