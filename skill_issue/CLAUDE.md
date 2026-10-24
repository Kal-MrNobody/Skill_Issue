# SkillAudit — rules for Claude Code

## What this is
SkillAudit checks an AI agent skill (a GitHub repo containing SKILL.md) before someone installs it and reports two things: can it be trusted, and does it actually help. It is five Fetch.ai uAgents registered on Agentverse; users reach it through ASI:One chat. v1 has no payments and no web frontend: the whole user workflow happens inside ASI:One.

## Agents (hub and spoke: workers only ever talk to the orchestrator)
- orchestrator: the only agent users talk to. Agent Chat Protocol + ASI:One interactive cards. Owns job state, deadlines, retries and spend limits.
- intake: GitHub URL → pinned commit → safe download → list SKILL.md files → parse manifests → extract claims.
- security: static scan by wrapping the cisco-ai-skill-scanner CLI → findings in four buckets → gate decision.
- benchmark: runs the skill in a Docker sandbox on a fixed suite, WITH and WITHOUT the skill, k repeats; watches runtime behaviour; caches baselines.
- report: two verdicts (trust, lift) + claims check + efficiency + provenance → JSON report + ASI:One card.

## Job flow
RECEIVED → INTAKE → (AWAITING_SKILL_PICK if several skills) → SCANNING → AWAITING_RUN_CLICK → BENCHMARKING → REPORTING → DONE
- Gate BLOCK, or no matching suite: SCANNING → REPORTING (security-only report) → DONE
- Any non-terminal state → FAILED(step, error_code)

## Hard rules
1. Agents communicate only through the message models in `contracts/`. Never define a message model anywhere else.
2. Every internal message carries `job_id`, `attempt` and `schema_version`. Every result carries a `Provenance`.
3. Logic lives in `core/` as pure functions (no network, no uagents imports). Agent handlers stay thin: validate → call core → send. Test core first.
4. Never execute, import or install anything from a scanned repo outside the Docker sandbox. Never `git clone` a scanned repo on the host: download the archive at the pinned commit into a temp dir and reject symlinks, hardlinks, absolute or `..` paths, oversized repos and large binaries.
5. Secrets (agent seeds, API keys) come only from environment variables. Never log them, never commit them, never put the model API key inside the sandbox (the sandbox talks to a key-injecting proxy).
6. Workers accept requests only from the orchestrator's address. The orchestrator accepts results only from registered worker addresses and ignores stale attempts.
7. Chat (orchestrator only): acknowledge every ChatMessage; send exactly one reply per user action; never send progress messages to ASI:One; put `job_id` and `action` in every card button selection; parse selections as JSON first and natural-language prose second; always send a useful text block alongside a card (invalid cards silently degrade to plain text).
8. Tests come first. Never weaken, skip or delete a test to make it pass. Stop and explain instead.
9. Test fixtures are inert: fake credentials, reserved domains (`*.example.invalid`), no working payloads. Never run fixture scripts outside the sandbox.
10. No letter grades and no composite score anywhere. Trust and lift are separate verdicts.
11. Python 3.12 with uv. `uagents>=0.25.5`, Agent Chat Protocol 0.3.0. Pin versions in pyproject.toml.
12. Messages carry references and summaries (repo, commit, ids, counts), never file contents. Each worker fetches the archive itself by (repo, pinned commit) using the shared safe-download function.

## Read before writing agent code (fetch these; do not rely on memory for these APIs)
- Agent Chat Protocol: https://innovationlab.fetch.ai/resources/docs/agent-communication/agent-chat-protocol
- Interactive cards (schemas, limits, selection formats, plain-Python client example): https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards
- Agent-to-agent messaging incl. send_and_receive: https://innovationlab.fetch.ai/resources/docs/agent-communication/uagent-uagent-communication
- Hosted vs local vs mailbox agents: https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation
- Reference architecture incl. ASI:One echo-loop protection: https://innovationlab.fetch.ai/resources/docs/examples/openclaw/openclaw-fetchai-orchestrator
- Examples repo: https://github.com/fetchai/innovation-lab-examples
- Scanner CLI: https://pypi.org/project/cisco-ai-skill-scanner/
- Paired skill benchmark (for later suites): https://huggingface.co/datasets/benchflow/skillsbench

## Commands
- Install: `uv sync`
- Unit tests: `uv run pytest -q`
- Integration tests: `uv run pytest -q -m integration`
- Live tests (cost money, only when I ask): `uv run pytest -q -m live`
- Lint/format: `uv run ruff check . && uv run ruff format --check .`

## How we work
One step of `docs/PLAN.md` per session. Plan → tests → smallest implementation that passes → lint → short report. If something in PLAN.md looks wrong or impossible, say so before building.
