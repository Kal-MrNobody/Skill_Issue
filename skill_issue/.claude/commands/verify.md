---
description: Verify a PLAN.md step against its acceptance tests (no edits)
---
Verify step $ARGUMENTS of docs/PLAN.md. Do not edit, create or delete any file.

1. Run lint, the unit suite, and the integration suite if the step lists integration tests.
2. For every acceptance test in the step, report PASS, FAIL or MISSING with evidence: the test name and the relevant output line.
3. Run the step's "See it work" command and show the relevant output.
4. List anything in the step's Build section that no test covers.
5. Confirm that no test was skipped, weakened or deleted compared with the last commit (check the git diff of tests/).

End with exactly one line: READY TO COMMIT or NOT READY: <reasons>.
