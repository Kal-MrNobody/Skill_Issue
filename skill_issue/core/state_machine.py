"""Job state machine: a pure lookup in an explicit transition table."""

from contracts.enums import JobEvent, JobState

S, E = JobState, JobEvent

TERMINAL = frozenset({S.DONE, S.FAILED})
NON_TERMINAL = frozenset(set(JobState) - TERMINAL)

TRANSITIONS: dict[tuple[JobState, JobEvent], JobState] = {
    (S.RECEIVED, E.START): S.INTAKE,
    (S.INTAKE, E.ONE_SKILL): S.SCANNING,
    (S.INTAKE, E.MANY_SKILLS): S.AWAITING_SKILL_PICK,
    (S.AWAITING_SKILL_PICK, E.SKILL_PICKED): S.SCANNING,
    (S.SCANNING, E.SCAN_PASSED): S.AWAITING_RUN_CLICK,
    (S.SCANNING, E.SCAN_BLOCKED): S.REPORTING,
    (S.SCANNING, E.NO_SUITE): S.REPORTING,
    (S.AWAITING_RUN_CLICK, E.RUN_CLICKED): S.BENCHMARKING,
    (S.BENCHMARKING, E.BENCH_DONE): S.REPORTING,
    (S.REPORTING, E.REPORT_DONE): S.DONE,
    **{(state, E.FAIL): S.FAILED for state in NON_TERMINAL},
}


class IllegalTransition(ValueError):
    def __init__(self, state: JobState, event: JobEvent):
        super().__init__(f"illegal transition: {state} --{event}-->")
        self.state = state
        self.event = event


def transition(state: JobState, event: JobEvent) -> JobState:
    try:
        return TRANSITIONS[(state, event)]
    except KeyError:
        raise IllegalTransition(state, event) from None
