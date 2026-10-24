"""Run the real scanner on every fixture and print caught / missed per fixture.

    uv run python -m scripts.detection_report

Honest numbers for the README: a miss is printed as a miss, never faked.
"""

from scripts.try_scan import scan_fixture

# fixture -> bucket the static scan should report (None: no static detection expected)
EXPECTED = {
    "F1_benign": None,
    "F4_hidden_instructions": "PROMPT_INJECTION",
    "F5_dangerous_shell": "DANGEROUS_COMMAND",
    "F6_undeclared_network": "NETWORK",
    "F7_canary_reader": None,  # runtime should catch this one (step 5)
    "F8_symlink": None,
    "F10_claims": None,
    "F11_test_tamper": "PROMPT_INJECTION",
}
SERIOUS = {"MEDIUM", "HIGH", "CRITICAL"}


def main() -> int:
    caught = expected = false_alarms = 0
    print(f"{'fixture':<24} {'expect':<18} {'got (MEDIUM+)':<40} result")
    for fixture, bucket in EXPECTED.items():
        out = scan_fixture(f"tests/fixtures/{fixture}")
        got = sorted({f["bucket"] for f in out["findings"] if f["severity"] in SERIOUS})
        if bucket is None:
            result = "ok (clean)" if not got else "FALSE ALARM?"
            false_alarms += bool(got)
        else:
            expected += 1
            hit = bucket in got
            caught += hit
            result = "CAUGHT" if hit else "MISSED"
        print(
            f"{fixture:<24} {bucket or '-':<18} {','.join(got) or '-':<40} {result}"
            f"  gate={out['gate']}"
        )
    print(f"\nstatic detection: {caught}/{expected} caught, {false_alarms} unexpected alarms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
