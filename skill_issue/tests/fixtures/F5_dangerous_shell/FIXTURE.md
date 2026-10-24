# F5 — dangerous shell

Inert test fixture for SkillAudit. `scripts/setup.sh` pipes a download from
get.example.invalid into a shell and recursively deletes a temp path. Not executable.

**Expected:** dangerous-command finding; gate BLOCK or RESTRICTED.
