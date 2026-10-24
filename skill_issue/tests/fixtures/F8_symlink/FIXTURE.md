# F8 — symlinks

Inert test fixture for SkillAudit. Contains two symlinks: `hostname -> /etc/hostname`
(absolute target) and `escape -> ../../outside` (escapes the repo).

**Expected:** both links refused at intake; a warning is shown.
