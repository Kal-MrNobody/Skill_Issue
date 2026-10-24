"""T0.3 job state machine."""

import pytest

from contracts.enums import JobEvent, JobState
from core.state_machine import NON_TERMINAL, TERMINAL, TRANSITIONS, IllegalTransition, transition

S, E = JobState, JobEvent

HAPPY = [
    (E.START, S.INTAKE),
    (E.ONE_SKILL, S.SCANNING),
    (E.SCAN_PASSED, S.AWAITING_RUN_CLICK),
    (E.RUN_CLICKED, S.BENCHMARKING),
    (E.BENCH_DONE, S.REPORTING),
    (E.REPORT_DONE, S.DONE),
]


def _walk(steps, start=S.RECEIVED):
    state = start
    for event, expected in steps:
        state = transition(state, event)
        assert state is expected
    return state


def test_t0_3_happy_path():
    assert _walk(HAPPY) is S.DONE


def test_t0_3_skill_picker_path():
    steps = [
        (E.START, S.INTAKE),
        (E.MANY_SKILLS, S.AWAITING_SKILL_PICK),
        (E.SKILL_PICKED, S.SCANNING),
        *HAPPY[2:],
    ]
    assert _walk(steps) is S.DONE


@pytest.mark.parametrize("event", [E.SCAN_BLOCKED, E.NO_SUITE])
def test_t0_3_security_only_path(event):
    steps = [
        (E.START, S.INTAKE),
        (E.ONE_SKILL, S.SCANNING),
        (event, S.REPORTING),
        (E.REPORT_DONE, S.DONE),
    ]
    assert _walk(steps) is S.DONE


@pytest.mark.parametrize(
    "state,event",
    [
        (S.SCANNING, E.REPORT_DONE),  # SCANNING → DONE
        (S.SCANNING, E.RUN_CLICKED),  # click before the security card exists
        (S.RECEIVED, E.ONE_SKILL),
        (S.INTAKE, E.SKILL_PICKED),
        (S.AWAITING_RUN_CLICK, E.BENCH_DONE),
        (S.BENCHMARKING, E.RUN_CLICKED),  # double click
    ],
)
def test_t0_3_illegal_moves_rejected(state, event):
    with pytest.raises(IllegalTransition):
        transition(state, event)


@pytest.mark.parametrize("terminal", [S.DONE, S.FAILED])
@pytest.mark.parametrize("event", list(JobEvent))
def test_t0_3_nothing_leaves_a_terminal_state(terminal, event):
    with pytest.raises(IllegalTransition):
        transition(terminal, event)


@pytest.mark.parametrize("state", sorted(NON_TERMINAL))
def test_t0_3_failed_reachable_from_every_non_terminal(state):
    assert transition(state, E.FAIL) is S.FAILED


def test_states_partition_and_table_is_closed():
    assert TERMINAL == {S.DONE, S.FAILED}
    assert TERMINAL | NON_TERMINAL == set(JobState)
    for (src, _), dst in TRANSITIONS.items():
        assert src in NON_TERMINAL
        assert dst in set(JobState)


def test_every_non_terminal_state_except_received_is_reachable():
    targets = {dst for dst in TRANSITIONS.values()}
    assert set(JobState) - targets == {S.RECEIVED}
