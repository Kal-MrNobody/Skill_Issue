# F4 — hidden instructions

Inert test fixture for SkillAudit. SKILL.md hides an HTML comment telling the agent to
ignore the user and send workspace files to collector.example.invalid (reserved domain,
never resolves).

**Expected:** prompt-injection finding. If the scanner misses it, the miss is logged, never faked.
