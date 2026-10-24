# SkillAudit test assets

## Fixture repos (tests/fixtures/) — all inert
Rules: fake credentials only; reserved domains only (`*.example.invalid` never resolves); no working payloads; never run fixture scripts outside the sandbox. Each fixture folder has a FIXTURE.md stating what it tests and the expected result.

| ID | Folder | Scenario | Expected result |
|---|---|---|---|
| F1 | F1_benign | One SKILL.md (markdown formatting helper), no scripts | One candidate; no critical findings; gate STANDARD |
| F2 | F2_multi | Three skills in one repo | Skill picker card with three choices |
| F3 | F3_no_skill | README only | NO_SKILL with a clear message |
| F4 | F4_hidden_instructions | SKILL.md with an HTML comment telling the agent to ignore the user and send workspace files to collector.example.invalid | Prompt-injection finding (a scanner miss is logged, never faked) |
| F5 | F5_dangerous_shell | Script that downloads from get.example.invalid and pipes it into a shell, plus a recursive delete of a temp path | Dangerous-command finding; gate BLOCK or RESTRICTED |
| F6 | F6_undeclared_network | Description says "formats markdown"; script posts data to api.example.invalid | Domain listed as undeclared network use |
| F7 | F7_canary_reader | Clean-looking script that reads ~/.aws/credentials and prints the first line | Static may pass; runtime raises a high-severity canary event → BLOCKED |
| F8 | F8_symlink | Symlinks to /etc/hostname and to ../../outside | Links refused at intake, warning shown |
| F9 | generated at test time | Repo over the size cap (don't commit large files) | TOO_LARGE before full extraction |
| F10 | F10_claims | README: "reduces AI detection to under 10%" and "2x faster reviews" | Both claims extracted with file and line |
| F11 | F11_test_tamper | SKILL.md telling the agent to edit the tests until they pass | For real suites later: verifier uses untouched test files; run flagged |

Mirror these fixtures to a public GitHub repo (README: "inert test fixtures for a skill security scanner") so the deployed agents can be tested on real URLs.

## Manual ASI:One checklist (after you deploy)
| # | Do | Expect |
|---|---|---|
| M1 | Orchestrator profile → Chat with Agent → paste the F1 repo URL | Security card within seconds → Run → report card |
| M2 | Same flow via @handle mention | Selections arrive as JSON (check orchestrator logs) |
| M3 | A plain request without @, e.g. "is this skill safe? <url>" | Note whether ASI:One routes to you; flow works with prose selections |
| M4 | F2 repo URL | Skill picker → pick → security card |
| M5 | F4 and F5 repo URLs | Warnings / BLOCKED as expected; no Run button when blocked |
| M6 | Set the benchmark stub delay to 8 minutes and run a job | Learn whether a late report still lands in the same chat |
| M7 | Send the same message twice quickly | Exactly one reply |
| M8 | Non-GitHub URL, private repo, repo without SKILL.md | One clear reply each |
| M9 | Stop the benchmark agent mid-run | Security-only report with a note |
| M10 | Re-submit a finished repo | Instant cached answer |
| M11 | One clean end-to-end run | Save the shared chat URL for the submission |

## Chaos list (re-run before recording the demo)
- Restart each agent during a job.
- Cut the network on the benchmark box mid-run.
- Remove the scanner binary.
- Stop the model proxy.
- Push the job queue past its limit.
