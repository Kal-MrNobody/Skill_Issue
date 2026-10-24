---
description: Build one step of docs/PLAN.md (plan → tests → code)
---
You are building step $ARGUMENTS of docs/PLAN.md.

1. Read CLAUDE.md and all of step $ARGUMENTS in docs/PLAN.md. Open only the existing files this step touches.
2. If the step uses uAgents, the Agent Chat Protocol, interactive cards, mailboxes or the scanner CLI, fetch the matching page listed in CLAUDE.md before writing code. Do not rely on memory for those APIs.
3. Present a plan, then stop and wait for my approval. The plan lists:
   - files to create or change
   - contract changes (any change to contracts/ needs a stated reason)
   - the test list: every acceptance test from the step, plus edge cases you think are missing
   - anything in the step you believe is wrong, risky or impossible
4. After I approve: write the tests first and run them. They should fail for the right reason.
5. Implement the smallest change that makes them pass. Logic goes in core/; handlers stay thin.
6. Run lint and the unit suite, plus integration tests if the step has them. Fix the code, not the tests. If a test looks wrong, stop and tell me why.
7. Finish with: what you built, test counts (passed / failed / skipped), what you stubbed or deferred, and the exact "See it work" command.
