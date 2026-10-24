"""Chat routing (pure): one incoming chat text → what the orchestrator should do with it.

Exactly one reply per user action: a new job or a selection gets its reply later, when the
flow notifies (picker, security card, report, failure). Everything else is answered here
right away, or dropped silently (duplicates, our own replies echoed back).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from contracts.enums import JobState
from core.cards import Reply
from core.chat_text import HELP_TEXT, extract_repo_url
from core.echo import EchoGuard, Verdict
from core.jobs import Job
from core.selection import JobView, Selection, parse_selection

WAITING = (JobState.AWAITING_SKILL_PICK, JobState.AWAITING_RUN_CLICK)

RETRY_TEXT = (
    "I didn't catch which option you picked. Use the buttons on the card, "
    "or reply with the skill id (or 'run benchmark')."
)
STALE_TEXT = "That card is no longer active. Send the repository link again to start a new audit."
COOLDOWN_TEXT = "I just started an audit for you. Please wait a few seconds before the next one."
TOO_MANY_TEXT = "You already have several audits running. I'll take a new one when one finishes."


@dataclass(frozen=True)
class Drop:
    reason: str


@dataclass(frozen=True)
class Say:
    reply: Reply


@dataclass(frozen=True)
class StartJob:
    repo_url: str


@dataclass(frozen=True)
class Select:
    job_id: str
    action: str
    skill_path: str | None = None


Action = Drop | Say | StartJob | Select


def _view(job: Job) -> JobView:
    return JobView(job.job_id, job.state, tuple(c["skill_id"] for c in job.candidates))


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except (ValueError, TypeError):
        return False
    return True


class ChatRouter:
    def __init__(self, guard: EchoGuard | None = None, dev_mode: bool = False) -> None:
        self.guard = guard or EchoGuard()
        self.dev_mode = dev_mode

    def route(self, sender: str, text: str, jobs: Sequence[Job], now: float) -> Action:
        """`jobs` are this sender's jobs (any state)."""
        verdict = self.guard.check(sender, text, now)
        if verdict is not Verdict.ACCEPT:
            return Drop(str(verdict))
        waiting = [j for j in jobs if j.state in WAITING]
        url = extract_repo_url(text, self.dev_mode)
        names_a_job = any(j.job_id in text for j in waiting)
        if url and not names_a_job and not _is_json(text):
            return self._new_job(sender, url, jobs, now)
        sel = parse_selection(text, [_view(j) for j in waiting])
        if sel is not None:
            return self._select(sel, jobs)
        if waiting:
            return Say(Reply(RETRY_TEXT))
        return Say(Reply(HELP_TEXT))

    def _new_job(self, sender: str, url: str, jobs: Sequence[Job], now: float) -> Action:
        active = sum(1 for j in jobs if not j.terminal)
        verdict = self.guard.may_start_job(sender, active, now)
        if verdict is Verdict.TOO_MANY:
            return Say(Reply(TOO_MANY_TEXT))
        if verdict is Verdict.COOLDOWN:
            return Say(Reply(COOLDOWN_TEXT))
        self.guard.job_started(sender, now)
        return StartJob(url)

    def _select(self, sel: Selection, jobs: Sequence[Job]) -> Action:
        job = next((j for j in jobs if j.job_id == sel.job_id), None)  # only the sender's own
        if job is None or job.state not in WAITING:
            return Say(Reply(STALE_TEXT))
        if sel.action == "pick_skill":
            if job.state is not JobState.AWAITING_SKILL_PICK:
                return Say(Reply(STALE_TEXT))
            path = next((c["path"] for c in job.candidates if c["skill_id"] == sel.skill_id), None)
            if path is None:
                return Say(Reply(RETRY_TEXT))
            return Select(job.job_id, "pick_skill", path)
        if job.state is not JobState.AWAITING_RUN_CLICK:
            return Say(Reply(STALE_TEXT))
        return Select(job.job_id, "run_benchmark")

    def sent(self, sender: str, text: str, now: float) -> None:
        """Remember what we replied so an echo of it is ignored."""
        self.guard.record_reply(sender, text, now)
