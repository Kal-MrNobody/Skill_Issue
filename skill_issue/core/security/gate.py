"""Gate policy (pure, table-driven). Fail safe: a failed scan is never STANDARD."""

from collections.abc import Iterable

from contracts.enums import GateDecision, Severity

# first matching row wins
POLICY: tuple[tuple[frozenset[Severity], GateDecision], ...] = (
    (frozenset({Severity.CRITICAL}), GateDecision.BLOCK),
    (frozenset({Severity.HIGH, Severity.MEDIUM}), GateDecision.RESTRICTED),
)


def gate_for(findings: Iterable, scan_failed: bool) -> GateDecision:
    severities = {f.severity for f in findings}
    for trigger, decision in POLICY:
        if severities & trigger:
            return decision
    return GateDecision.RESTRICTED if scan_failed else GateDecision.STANDARD
