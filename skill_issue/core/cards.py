"""ASI:One interactive card builders (pure) + a validator for the documented card schemas.

Every reply has a useful plain-text block: invalid cards silently degrade to that text.
Every button selection carries job_id and action. No letter grades, no composite score.
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from contracts.enums import ErrorCode, GateDecision
from core.jobs import Job

MAX_PAYLOAD_BYTES = 64 * 1024
MAX_CUSTOM_DEPTH = 8
CARD_KINDS = {"carousel", "detail", "form", "review", "custom"}
BADGE_VARIANTS = {"info", "success", "warning"}
TEXT_STYLES = {"body", "muted", "emphasis"}
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
DISCLAIMER = "Best-effort check, not a guarantee: no finding does not mean no risk."


@dataclass(frozen=True)
class Reply:
    text: str
    card_kind: str | None = None
    payload: dict[str, Any] | None = None
    terminal: bool = False


class CardError(ValueError):
    pass


def card_metadata(reply: Reply) -> dict[str, str]:
    meta = {
        "card_protocol_version": "1",
        "requires_card_interaction": "true",
        "card_kind": reply.card_kind or "",
        "card_payload": json.dumps(reply.payload),
        "preferred_drawer_width_px": "540",
    }
    if reply.terminal:
        meta["is_terminal"] = "true"
    return meta


# --- validation ---------------------------------------------------------------


def _req(cond: bool, why: str) -> None:
    if not cond:
        raise CardError(why)


def _is_str(v) -> bool:
    return isinstance(v, str) and v != ""


def _cta(cta, where: str) -> None:
    _req(isinstance(cta, dict), f"{where}: cta must be an object")
    _req(_is_str(cta.get("label")), f"{where}: cta needs a label")
    _req(isinstance(cta.get("selection"), dict), f"{where}: cta needs a selection object")


def _rows(rows, where: str) -> None:
    _req(isinstance(rows, list), f"{where}: summary_rows must be a list")
    for r in rows:
        _req(isinstance(r, dict) and _is_str(r.get("label")), f"{where}: row needs a label")
        _req(isinstance(r.get("value"), str), f"{where}: row value must be a string")


def _badges(badges, where: str) -> None:
    for b in badges or []:
        _req(_is_str(b.get("label")), f"{where}: badge needs a label")
        _req(b.get("variant", "info") in BADGE_VARIANTS, f"{where}: bad badge variant")


def _element(node, depth: int) -> None:
    _req(depth <= MAX_CUSTOM_DEPTH, f"custom tree deeper than {MAX_CUSTOM_DEPTH} levels")
    _req(isinstance(node, dict), "custom element must be an object")
    t = node.get("type")
    kids: list = []
    if t in ("section", "group"):
        kids = node.get("children")
        _req(isinstance(kids, list), f"{t} needs children")
        if t == "group":
            _req(node.get("direction") in ("row", "column"), "group needs direction row|column")
    elif t == "divider":
        pass
    elif t == "text":
        _req(isinstance(node.get("value"), str), "text needs a value")
        _req(node.get("style", "body") in TEXT_STYLES, "bad text style")
    elif t == "heading":
        _req(_is_str(node.get("value")), "heading needs a value")
        _req(node.get("level", 2) in (1, 2, 3), "heading level must be 1-3")
    elif t == "image":
        _req(_is_str(node.get("src")), "image needs src")
    elif t == "badge":
        _badges([node], "badge")
    elif t == "button":
        _req(_is_str(node.get("label")), "button needs a label")
        _req(isinstance((node.get("action") or {}).get("selection"), dict), "button needs action")
    elif t == "input":
        _req(_is_str(node.get("name")) and _is_str(node.get("label")), "input needs name+label")
    elif t == "list":
        items = node.get("items")
        _req(isinstance(items, list), "list needs items")
        for item in items:
            _req(isinstance(item.get("children"), list), "list item needs children")
            kids = kids + item["children"]
    elif t == "choice_grid":
        _req(_is_str(node.get("name")) and isinstance(node.get("choices"), list), "bad grid")
    else:
        raise CardError(f"unknown custom element type {t!r}")
    for child in kids:
        _element(child, depth + 1)


def validate_card(kind: str, payload: dict) -> None:
    """Check a payload against the documented schema for its card_kind. Raises CardError."""
    _req(kind in CARD_KINDS, f"unknown card_kind {kind!r}")
    _req(isinstance(payload, dict), "payload must be an object")
    _req(len(json.dumps(payload).encode()) <= MAX_PAYLOAD_BYTES, "payload over 64 KB")
    if kind == "carousel":
        _req(_is_str(payload.get("title")), "carousel needs a title")
        items = payload.get("items")
        _req(isinstance(items, list) and items, "carousel needs items")
        for it in items:
            _req(_is_str(it.get("id")) and _is_str(it.get("title")), "item needs id and title")
            _cta(it.get("primary_cta"), "carousel item")
            _badges(it.get("badges"), "carousel item")
    elif kind == "detail":
        _req(_is_str(payload.get("title")), "detail needs a title")
        _rows(payload.get("summary_rows", []), "detail")
        _req(isinstance(payload.get("ctas"), list), "detail needs ctas")
        for c in payload["ctas"]:
            _cta(c, "detail")
    elif kind == "form":
        _req(_is_str(payload.get("title")) and isinstance(payload.get("fields"), list), "bad form")
        _cta(payload.get("submit_cta"), "form")
    elif kind == "review":
        _req(_is_str(payload.get("title")), "review needs a title")
        _rows(payload.get("summary_rows", []), "review")
        _cta(payload.get("approve_cta"), "review")
        _cta(payload.get("reject_cta"), "review")
    else:
        _req(set(payload) == {"root"}, "custom payload must be exactly {'root': element}")
        _element(payload["root"], 1)


def iter_selections(kind: str, payload: dict) -> Iterator[dict]:
    if kind == "carousel":
        for it in payload.get("items", []):
            yield it["primary_cta"]["selection"]
    elif kind == "detail":
        for c in payload.get("ctas", []):
            yield c["selection"]
    elif kind == "form":
        yield payload["submit_cta"]["selection"]
    elif kind == "review":
        yield payload["approve_cta"]["selection"]
        yield payload["reject_cta"]["selection"]
    elif kind == "custom":
        stack = [payload["root"]]
        while stack:
            node = stack.pop()
            if node.get("type") == "button":
                yield node["action"]["selection"]
            for item in node.get("items", []) if node.get("type") == "list" else []:
                if item.get("action"):
                    yield item["action"]["selection"]
                stack += item.get("children", [])
            stack += node.get("children", []) if node.get("type") != "list" else []


# --- helpers -------------------------------------------------------------------


def _fit(build: Callable[[int], dict], n: int) -> dict:
    """Largest payload built from the first k ≤ n items that stays under 64 KB."""
    while True:
        payload = build(n)
        if len(json.dumps(payload).encode()) <= MAX_PAYLOAD_BYTES or n == 0:
            return payload
        n //= 2


def _short(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _repo(job: Job) -> str:
    sha = (job.commit_sha or "")[:7]
    return f"{job.repo_url} @ {sha}" if sha else job.repo_url


def _skill_name(job: Job) -> str:
    for c in job.candidates:
        if c["path"] == job.skill_path:
            return c["name"]
    return job.skill_path or "skill"


def _sorted_findings(job: Job) -> list[dict]:
    findings = list((job.scan or {}).get("findings") or [])
    return sorted(findings, key=lambda f: SEVERITY_ORDER.index(str(f["severity"])))


def _counts(findings: list[dict]) -> str:
    counts = {s: 0 for s in SEVERITY_ORDER}
    for f in findings:
        counts[str(f["severity"])] += 1
    parts = [f"{n} {s}" for s, n in counts.items() if n]
    return ", ".join(parts) or "no findings"


def _where(f: dict) -> str:
    return f"{f['file']}:{f.get('line') or 1}"


def estimate_minutes(tasks: int = 3, k: int = 3, seconds_per_run: int = 40) -> int:
    return max(1, round(tasks * 2 * k * seconds_per_run / 60))


# --- replies ---------------------------------------------------------------------


def reply_for(job: Job, kind: str, k: int = 3) -> Reply:
    if kind == "pick_skill":
        return _picker(job)
    if kind == "run_benchmark":
        return _security(job, estimate_minutes(k=k))
    if kind == "done":
        return _report(job)
    return _failure(job)


def _picker(job: Job) -> Reply:
    cands = job.candidates

    def build(n: int) -> dict:
        return {
            "title": "Pick a skill to audit",
            "subtitle": _short(f"{_repo(job)} · {len(cands)} skills", 120),
            "items": [
                {
                    "id": c["skill_id"],
                    "title": _short(c["name"], 80),
                    "subtitle": _short(c["path"], 100),
                    "secondary_text": _short(c["description"] or "No description", 160),
                    "badges": [{"label": f"{len(c.get('files') or [])} files", "variant": "info"}],
                    "primary_cta": {
                        "label": "Audit this skill",
                        "selection": {
                            "job_id": job.job_id,
                            "action": "pick_skill",
                            "skill_id": c["skill_id"],
                        },
                    },
                }
                for c in cands[: max(n, 1)]
            ],
        }

    lines = [f"- {c['name']} ({c['path']}), id {c['skill_id']}" for c in cands[:30]]
    text = (
        f"I found {len(cands)} skills in {_repo(job)}. Which one should I audit?\n"
        + "\n".join(lines)
        + "\nPick one on the card, or reply with its id."
    )
    return Reply(text, "carousel", _fit(build, min(len(cands), 30)))


def _security(job: Job, minutes: int) -> Reply:
    scan = job.scan or {}
    gate = str(scan.get("gate"))
    findings = _sorted_findings(job)
    serious = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH", "MEDIUM")]
    undeclared = scan.get("undeclared_domains") or []
    version = (scan.get("provenance") or {}).get("tool_versions", {}).get("cisco-ai-skill-scanner")

    def build(n: int) -> dict:
        rows = [
            {"label": "Skill", "value": _short(f"{_skill_name(job)} ({job.skill_path})", 200)},
            {"label": "Repository", "value": _short(_repo(job), 200)},
            {"label": "Gate", "value": gate},
            {"label": "Findings", "value": _counts(findings)},
        ]
        for f in serious[:n]:
            rows.append(
                {
                    "label": f"{f['severity']} · {f['bucket']}",
                    "value": _short(f"{_where(f)} {f['message']}", 240),
                }
            )
        if undeclared:
            rows.append(
                {"label": "Undeclared network", "value": _short(", ".join(undeclared), 240)}
            )
        if scan.get("scan_error"):
            rows.append({"label": "Note", "value": "The scanner failed, so the gate fails safe."})
        if gate == GateDecision.RESTRICTED:
            rows.append({"label": "Benchmark", "value": "Will run with no network access."})
        if version:
            rows.append({"label": "Scanner", "value": f"cisco-ai-skill-scanner {version}"})
        return {
            "title": _short(f"Security scan: {_skill_name(job)}", 100),
            "summary_rows": rows,
            "ctas": [
                {
                    "label": f"Run benchmark (~{minutes} min)",
                    "primary": True,
                    "selection": {"job_id": job.job_id, "action": "run_benchmark"},
                }
            ],
        }

    top = "; ".join(f"{f['severity']} {f['bucket']} at {_where(f)}" for f in serious[:3])
    text = (
        f"Security scan for {_skill_name(job)} ({_repo(job)}): gate {gate}, {_counts(findings)}."
        + (f" Top: {top}." if top else "")
        + (f" Undeclared network: {', '.join(undeclared[:5])}." if undeclared else "")
        + f" Reply 'run benchmark' to measure whether it helps (~{minutes} min)."
    )
    return Reply(text, "detail", _fit(build, min(len(serious), 12)))


def _report(job: Job) -> Reply:
    rep = job.report or {}
    card = rep.get("card") or {}
    text = _report_text(job)
    if card.get("kind") and card.get("payload"):
        try:
            validate_card(card["kind"], card["payload"])
            return Reply(text, card["kind"], card["payload"], terminal=True)
        except CardError:
            pass  # fall back to our own card
    trust, lift = str(rep.get("trust")), str(rep.get("lift"))
    findings = _sorted_findings(job)

    def build(n: int) -> dict:
        children: list[dict] = [
            {
                "type": "group",
                "direction": "row",
                "children": [
                    {"type": "badge", "label": f"Trust: {trust}", "variant": _variant(trust)},
                    {"type": "badge", "label": f"Lift: {lift}", "variant": _variant(lift)},
                ],
            },
            {"type": "text", "value": _short(rep.get("text") or "", 2000)},
            {"type": "heading", "value": "Security findings", "level": 3},
        ]
        items = [
            {
                "children": [
                    {
                        "type": "text",
                        "value": f"{f['severity']} · {f['bucket']}",
                        "style": "emphasis",
                    },
                    {
                        "type": "text",
                        "value": _short(f"{_where(f)} {f['message']}", 240),
                        "style": "muted",
                    },
                ]
            }
            for f in findings[:n]
        ]
        if items:
            children.append({"type": "list", "items": items})
        else:
            children.append({"type": "text", "value": "No static findings.", "style": "muted"})
        children += [{"type": "divider"}, {"type": "text", "value": DISCLAIMER, "style": "muted"}]
        return {
            "root": {
                "type": "section",
                "title": _short(f"SkillAudit: {_skill_name(job)}", 100),
                "subtitle": _short(_repo(job), 120),
                "children": children,
            }
        }

    return Reply(text, "custom", _fit(build, min(len(findings), 25)), terminal=True)


def _variant(verdict: str) -> str:
    if verdict in ("NOTHING_OBSERVED", "HELPS"):
        return "success"
    if verdict in ("BLOCKED", "WARNINGS", "HURTS"):
        return "warning"
    return "info"


def _report_text(job: Job) -> str:
    rep = job.report or {}
    findings = _sorted_findings(job)
    serious = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH", "MEDIUM")]
    top = "; ".join(f"{f['severity']} {f['bucket']} at {_where(f)}" for f in serious[:3])
    return (
        f"Audit of {_skill_name(job)} ({_repo(job)}). Trust: {rep.get('trust')}. "
        f"Lift: {rep.get('lift')}. {rep.get('text') or ''}".strip()
        + (f" Findings: {top}." if top else "")
        + f" {DISCLAIMER}"
    )


FAILURE_HINTS = {
    ErrorCode.BAD_URL: "Send a GitHub repo link like https://github.com/owner/repo",
    ErrorCode.REPO_NOT_FOUND: "Check the link; only public GitHub repositories are supported.",
    ErrorCode.PRIVATE_REPO: "Only public GitHub repositories are supported.",
    ErrorCode.NO_SKILL: "A skill repository needs at least one SKILL.md file.",
    ErrorCode.TOO_LARGE: "The repository is over the size limit for an audit.",
    ErrorCode.UNSAFE_ARCHIVE: "The repository archive contained unsafe paths, so I stopped.",
    ErrorCode.RATE_LIMITED: "GitHub is rate limiting me. Please try again in a few minutes.",
    ErrorCode.TIMEOUT: "One of my steps took too long. Please try again.",
    ErrorCode.BUDGET_EXHAUSTED: "Today's benchmark budget is used up. Please try tomorrow.",
}


def _failure(job: Job) -> Reply:
    f = job.failure
    if f is None:
        return Reply("Sorry, something went wrong with this audit. Please try again.")
    hint = FAILURE_HINTS.get(f.code, "Please try again later.")
    detail = f" {f.detail}" if f.detail else ""
    return Reply(f"Sorry, I couldn't finish the audit of {job.repo_url} ({f.code}).{detail} {hint}")
