# SkillAudit build plan — v1 (security + benchmark)

## How to use this file
One step per Claude Code session:
1. `/clear`
2. `/step N` → read the plan it proposes, edit or approve it
3. let it write tests first, then code
4. `/verify N` → must end with READY TO COMMIT
5. `/review` → fix anything it flags
6. `git add -A && git commit -m "step N: <title>"`

Never start step N+1 before step N is READY. Fixture IDs (F1–F11) refer to docs/TESTING.md.

## Message flow (hub and spoke)
```
user ──repo link──────────────▶ orchestrator
orchestrator ──IntakeRequest──▶ intake ──IntakeResult──▶ orchestrator
   (several skills → skill picker card → user picks one)
orchestrator ──ScanRequest────▶ security ──ScanResult──▶ orchestrator
orchestrator ──security card + "Run benchmark" button──▶ user
user click ───────────────────▶ orchestrator ──BenchRequest──▶ benchmark
benchmark ──BenchAccepted, Heartbeat…, BenchResult──▶ orchestrator
orchestrator ──ReportRequest──▶ report ──ReportResult──▶ orchestrator
orchestrator ──report card────▶ user
```

---

## Step 0 — Scaffold, contracts, fixtures
**Goal:** the repo skeleton and the shared language all five agents speak.

**Build**
- uv project on Python 3.12. Runtime deps: `uagents>=0.25.5`, `uagents-core`, `httpx`, `pydantic`. Dev deps: `pytest`, `pytest-asyncio`, `ruff`. Register pytest markers `integration` and `live`.
- Folders: `contracts/`, `core/`, `agents/{orchestrator,intake,security,benchmark,report}/`, `sandbox/`, `suites/`, `scripts/`, `tests/{unit,integration,fixtures}/`.
- `contracts/`: every inter-agent message (IntakeRequest/IntakeResult, ScanRequest/ScanResult, BenchRequest, BenchAccepted, Heartbeat, BenchResult, ReportRequest/ReportResult, Failure), shared enums (JobState, ErrorCode, Severity, Bucket, GateDecision, TrustVerdict, LiftVerdict) and a Provenance model. Every message has `job_id`, `attempt`, `schema_version`.
- Error codes: BAD_URL, REPO_NOT_FOUND, PRIVATE_REPO, NO_SKILL, TOO_LARGE, UNSAFE_ARCHIVE, SCAN_FAILED, NO_SUITE, SANDBOX_ERROR, TIMEOUT, RATE_LIMITED, BUDGET_EXHAUSTED, INTERNAL.
- `core/state_machine`: pure `transition(state, event) -> state` driven by an explicit table (job flow in CLAUDE.md).
- `tests/fixtures/`: create the inert fixture repos F1–F8, F10, F11 described in docs/TESTING.md, each with a FIXTURE.md (F9 is generated at test time).
- `.env.example` listing every variable (one seed per agent, AGENTVERSE_API_KEY, MODEL_BASE_URL, MODEL_API_KEY, MODEL_ID, optional GITHUB_TOKEN) and a `.gitignore` covering `.env`.

**Acceptance tests**
- T0.1 every contract model round-trips (serialize → parse) unchanged.
- T0.2 building any internal message without job_id, attempt or schema_version fails validation.
- T0.3 the happy path RECEIVED → … → DONE is accepted; illegal moves (e.g. SCANNING → DONE, anything out of DONE) are rejected; FAILED is reachable from every non-terminal state.
- T0.4 each fixture contains what its scenario needs (F2 has three SKILL.md files, F3 has none, F8 contains symlinks, …).
- T0.5 lint passes; no key-like strings in tracked files.

**See it work:** `uv run pytest -q`

---

## Step 1 — Orchestrator core + stub workers in one local Bureau
**Goal:** a fake job flows end to end through all five agents in one process.

**Build**
- `core/jobs`: job store behind an interface (in-memory now, agent storage later), per-step deadlines, attempt counter, idempotency key = job_id + step + attempt.
- Each worker as a uAgent with a stub handler returning canned results. Stub behaviour (delay, fail, go silent) configurable for tests.
- The orchestrator drives the flow. In this step the "Run benchmark" click is simulated automatically.
- Benchmark is asynchronous: BenchAccepted immediately, Heartbeat every N seconds, then BenchResult. The orchestrator never blocks a handler waiting for it. Fast hops (intake, security, report) may use request/response with a timeout.
- Sender allowlists: workers drop messages that are not from the orchestrator; the orchestrator drops results from unknown senders or stale attempts.
- `scripts/run_local`: all five agents in one Bureau with local endpoints. One structured log line per event, always including job_id and agent name.

**Acceptance tests (integration)**
- T1.1 happy path: a job reaches DONE; logs show intake → security → benchmark → report in order.
- T1.2 each worker in fail mode → job ends FAILED with the right step and error code; nothing hangs.
- T1.3 benchmark stub goes silent past its deadline → FAILED(BENCHMARKING, TIMEOUT).
- T1.4 the same IntakeRequest delivered twice → the work is done once.
- T1.5 a message to a worker from an unknown address is dropped and logged.
- T1.6 heartbeats extend the benchmark deadline; no heartbeats → timeout.
- T1.7 two concurrent jobs never mix state.

**See it work:** `uv run python -m scripts.run_local`

---

## Step 2 — Intake agent
**Goal:** GitHub URL → pinned, safely downloaded, parsed skill candidates plus claims.

**Build**
- `core/intake/url`: parse github.com/owner/repo, /tree/<ref>/<path>, trailing slashes, `.git` suffix; reject everything else with BAD_URL.
- Source interface: GitHubSource (resolve ref → 40-char commit SHA, list tree, download the archive at that SHA; optional GITHUB_TOKEN) and LocalSource (fixture folders; tests and dev mode only).
- `core/intake/safe_extract`, reused by every worker: rejects symlinks, hardlinks, absolute and `..` paths; checks size and file-count caps before full extraction; skips large binaries; caches by commit.
- Find every SKILL.md; parse frontmatter (name, description) and body; list scripts/resources per skill; stable skill_id per path.
- Claims extraction v1 = rules: measurable statements (percentages, multipliers, "reduces / improves / detects / prevents") from README and SKILL.md, each with file and line. Leave a seam for an LLM extractor later.
- IntakeResult: commit SHA, candidates, claims, warnings.

**Acceptance tests**
- T2.1 F1 → one candidate with parsed name and description.
- T2.2 F2 → three candidates; skill_ids stable across runs.
- T2.3 F3 → Failure(NO_SKILL) with a human-readable message.
- T2.4 F8 → links refused, warning recorded, nothing written outside the temp dir.
- T2.5 F9 (generated oversize repo) → Failure(TOO_LARGE) before full extraction.
- T2.6 a table of at least 12 URL forms → parsed or BAD_URL as expected.
- T2.7 F10 → both claims extracted with file and line.
- T2.8 (live) a real public skill repo resolves to a 40-character commit SHA.

**See it work:** `uv run python -m scripts.try_intake <github-url-or-fixture-path>`

---

## Step 3 — Security agent (static)
**Goal:** real static findings, normalized into buckets, plus a gate decision.

**Build**
- Wrap the `cisco-ai-skill-scanner` CLI (read its docs first): behavioural analyzer on, LLM analyzer optional via env, hard timeout, SARIF output.
- `core/security/normalize`: SARIF → findings {bucket: prompt_injection | dangerous_command | network | install_persistence | other, severity, file, line, message, rule_id, source}; dedupe.
- Domain inventory (informational, not a detector): every URL/domain referenced in SKILL.md and scripts, marked "undeclared" when the skill's description doesn't mention network use.
- `core/security/gate` (pure, table-driven): any critical → BLOCK; any high or medium → RESTRICTED (benchmark later runs with no network); otherwise STANDARD.
- Scanner crash or timeout → status SCAN_FAILED with gate RESTRICTED (fail safe, never fail open).
- Provenance: scanner name and version.
- `scripts/detection_report`: runs the real scanner on every fixture and prints caught/missed per fixture. This seeds honest detection numbers for the README.

**Acceptance tests**
- T3.1 normalization against golden SARIF files (recorded once from real scans): expected buckets, severities, file and line. Logic tests never call the real scanner.
- T3.2 the gate policy table covers every severity mix.
- T3.3 simulated scanner timeout/crash → SCAN_FAILED + RESTRICTED; the job continues.
- T3.4 (integration) the real scanner runs on every fixture without crashing and returns valid output.
- T3.5 F6 → api.example.invalid appears in the domain inventory, marked undeclared.
- T3.6 every finding shown to users has a file and line.

**See it work:** `uv run python -m scripts.try_scan tests/fixtures/F5_dangerous_shell`

---

## Step 4 — Orchestrator chat layer + ASI:One cards
**Goal:** the full user flow works from a chat client, with stub benchmark and report.

**Build**
- Agent Chat Protocol on the orchestrator only, manifest published. Acknowledge every ChatMessage; handle start/end session content; pull the GitHub URL out of free text. Dev mode only: also accept a fixture path.
- `core/cards` (pure builders): skill picker (carousel) when there are several skills; security card with a findings summary and a "Run benchmark" button showing estimated time; final report card; a plain-text fallback for each. Every button selection includes job_id and action. Check schemas, the 64 KB payload limit and the 8-level custom-tree limit against the cards doc.
- `core/selection`: parse JSON first; fall back to prose written by ASI:One's planner (find job_id, action and skill_id inside a sentence).
- Echo guards: drop exact duplicate texts per sender within a window; drop messages that match our own last reply; per-sender cooldown before a new job; cap concurrent jobs per sender.
- Exactly one reply per user action; never send progress messages to the chat.
- `scripts/fake_asi1`: a local client adapted from the cards doc's plain-Python client. It sends a message, prints every card and auto-clicks the primary button. `--mode json|prose` controls how selections are sent back.

**Acceptance tests**
- T4.1 every card payload validates against its schema; size ≤ 64 KB; custom trees ≤ 8 levels.
- T4.2 every button selection contains job_id and action.
- T4.3 selection parser: JSON → parsed; prose such as "The user picked skill skl_2 for job j_8f3 and wants to run the benchmark" → parsed; garbage → one reply asking the user to try again.
- T4.4 a duplicate message inside the window → no second reply.
- T4.5 our own reply sent back to us as a new message → ignored.
- T4.6 F2 → skill picker first; picking leads to the security card.
- T4.7 gate BLOCK → no Run button; security-only report.
- T4.8 fake_asi1 reaches the final report card in both json and prose modes.
- T4.9 a message with no URL → one helpful reply with an example.

**See it work:** `uv run python -m scripts.fake_asi1 tests/fixtures/F2_multi --mode prose`

---

## Step 5 — Benchmark agent (sandbox + toy suite)
**Goal:** paired, repeated runs inside Docker with runtime watching. Real suites come later.

**Build**
- `sandbox/`: a Docker image and two profiles. STANDARD: egress only to the model proxy. RESTRICTED: no network at all. Both: read-only root, writable workspace, CPU/memory/time limits, canary files with obviously fake values (fake ~/.aws/credentials, fake .env, fake SSH key).
- Model key proxy outside the container: the container only gets the proxy URL; the proxy adds MODEL_API_KEY and counts tokens per run. Model settings come from env (MODEL_BASE_URL, MODEL_ID).
- Runtime watch per run: process spawns, file access outside the workspace (canary access highlighted), network attempts (allowed/blocked), package installs → a list of RuntimeEvents.
- Harness: a minimal agent loop (model + a shell tool inside the container). In the "with" condition the skill is mounted read-only and offered to the agent; record whether the agent actually used it.
- Suite interface: suite_id, version, tasks (prompt, input files, deterministic check). Ship a `toy` suite of three tiny deterministic tasks. Leave a seam for SkillsBench-style tasks, and verify results only with files the agent could not modify.
- Paired runs: each task × {without, with} × k (default 3). The "without" baseline is cached by (suite version, model id, harness version); on a cache hit only "with" runs execute.
- Protocol: BenchAccepted at once, Heartbeat with progress every N seconds, BenchResult with per-run outcomes, usage flags, tokens, durations, runtime events and provenance. Hard time cap per job; partial results on timeout.
- Tests use a fake model server with scripted responses. Real model calls only under `-m live`.

**Acceptance tests**
- T5.1 toy suite + fake model: the result shape is tasks × conditions × k, outcomes filled.
- T5.2 a second skill on the same suite/model executes zero "without" runs.
- T5.3 checked from inside a run: MODEL_API_KEY is in no environment variable or file in the container.
- T5.4 RESTRICTED: a network attempt from inside is blocked and logged as a RuntimeEvent.
- T5.5 F7 reading the canary file → a high-severity RuntimeEvent, even though the static scan was clean.
- T5.6 a run over the time cap is killed and marked TIMEOUT; the job still returns partial results.
- T5.7 heartbeats arrive on schedule during a job and stop after BenchResult.
- T5.8 (live) real model, toy suite, k=1 completes and records tokens.

**See it work:** `uv run python -m scripts.try_bench tests/fixtures/F1_benign --suite toy`

---

## Step 6 — Report agent
**Goal:** two verdicts, a claims check, efficiency and provenance as JSON plus the final card.

**Build**
- `core/scoring` (pure): per task, compare with vs without across k runs → win/loss/tie with consistency. Lift verdict: HELPS / NO_CLEAR_EFFECT / HURTS / NOT_APPLICABLE (skill never used, or no suite). Write the decision rule into the report itself.
- Trust verdict: BLOCKED (critical static finding or high-severity runtime event) / WARNINGS / NOTHING_OBSERVED. Show static evidence (file:line) next to runtime evidence (task, event), plus the sandbox profile used.
- Claims check: each claim → REPRODUCED / NOT_REPRODUCED / UNTESTED (most are UNTESTED in v1 unless a suite metric matches).
- Efficiency: extra tokens and seconds per task (with minus without).
- Provenance: repo, commit, skill path, scanner version, suite id + version, model id, harness version, k, timestamps.
- Output: the full JSON report saved under a stable id + a card payload ≤ 64 KB with a text fallback.

**Acceptance tests (table-driven)**
- T6.1 consistent 6/8 with vs 4/8 without across 3 runs → HELPS.
- T6.2 inconsistent or overlapping results → NO_CLEAR_EFFECT.
- T6.3 consistently worse with the skill → HURTS, with the regressing tasks listed.
- T6.4 skill never used by the agent → NOT_APPLICABLE, not "no effect".
- T6.5 critical static finding → BLOCKED regardless of lift.
- T6.6 clean static + canary RuntimeEvent → BLOCKED with the runtime evidence.
- T6.7 the JSON has every provenance field; the card is ≤ 64 KB.
- T6.8 the output contains no letter grade and no composite score.

**See it work:** `uv run python -m scripts.try_report tests/fixtures/sample_bench_result.json`

---

## Step 7 — Split into five deployable agents
**Goal:** five independent processes, each ready to connect to Agentverse as a mailbox agent.

**Build**
- One entrypoint per agent. Config from env: seed, port, mailbox on/off, peer addresses. Refuse to start without a seed; never log it; print the agent's address on startup.
- A peer address registry (env or config file) feeds the sender allowlists.
- Only the orchestrator includes the Agent Chat Protocol.
- A README per agent: short task-oriented name (under 20 characters), purpose, inputs/outputs, example prompts (orchestrator), keywords, the Innovation Lab and hackathon badges, address. The root README lists all five agents with names and addresses, plus a "v2: Payment Protocol" roadmap line.
- `scripts/run_split`: start all five as separate local processes without mailboxes.

**Acceptance tests**
- T7.1 every agent refuses to start without its seed and never prints it.
- T7.2 split mode: the fake_asi1 full flow passes with five processes.
- T7.3 each worker drops a message from a rogue local agent that isn't in the registry.
- T7.4 killing the benchmark process mid-job → orchestrator FAILED(BENCHMARKING, TIMEOUT); the user gets a security-only report with a note.
- T7.5 READMEs contain both badges and no secrets.

**See it work:** `uv run python -m scripts.run_split`, then `uv run python -m scripts.fake_asi1 tests/fixtures/F1_benign`

→ **Hand-off:** deploy (each agent with mailbox on, connected through its Inspector link), then run the manual checklist in docs/TESTING.md.

---

## Step 8 — Spend guards and chaos
**Goal:** safe to leave running in public with no payments.

**Build**
- Report cache keyed by (commit, skill path, suite version, model id): repeat requests answer instantly.
- Per-sender job limits, a global daily token budget, a queue with a maximum number of concurrent benchmark jobs.
- A restart-safe job store and a sweeper that fails stale jobs.
- A README section on degradation: what users get when each agent is down.

**Acceptance tests**
- T8.1 the same repo + commit twice → the second answer comes from cache with no worker calls.
- T8.2 a sender over the limit → one polite reply, no job created.
- T8.3 daily budget exhausted → benchmark refused, security-only report.
- T8.4 the orchestrator restarts mid-job → the job resumes or fails cleanly, never stuck.
- T8.5 20 concurrent fake jobs → no cross-talk, queue limit respected.
