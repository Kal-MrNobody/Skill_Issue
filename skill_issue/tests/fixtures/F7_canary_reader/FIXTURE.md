# F7 — canary reader

Inert test fixture for SkillAudit. A clean-looking script reads ~/.aws/credentials and
prints the first line. Inside the sandbox that path holds a canary file with fake values.

**Expected:** the static scan may pass; at runtime a high-severity canary event → BLOCKED.
