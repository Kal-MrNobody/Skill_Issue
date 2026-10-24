---
description: Review uncommitted changes against the hard rules in CLAUDE.md
---
Review the uncommitted changes (`git diff` plus new files) against the hard rules in CLAUDE.md. If you can, run the review in a fresh subagent with read-only tools so it doesn't inherit this session's assumptions. Do not change any files.

Check especially for:
- message models defined outside contracts/
- anything from a scanned repo executed, imported or installed outside the sandbox; any git clone of a scanned repo
- secrets in code, logs, test output or fixtures, or passed into the sandbox
- worker handlers missing the sender allowlist check
- chat paths that could reply more than once per user action, or that send progress messages to ASI:One
- card buttons missing job_id or action
- logic inside handlers that belongs in core/
- tests that were weakened, skipped or deleted
- letter grades or composite scores

Output a table: rule | file:line | problem | fix. If nothing is wrong, say so in one line.
