"""Card selections from ASI:One: JSON first (direct @mention), planner prose second."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from contracts.enums import JobState

ACTIONS = {"pick_skill", "run_benchmark"}
RUN_WORDS = re.compile(r"run_benchmark|\b(run|benchmark|start|go)\b", re.I)


@dataclass(frozen=True)
class JobView:
    """What the parser may know about one of the sender's jobs that is waiting for input."""

    job_id: str
    state: JobState
    skill_ids: tuple[str, ...]
    skill_names: tuple[str, ...] = ()  # same order as skill_ids


@dataclass(frozen=True)
class Selection:
    job_id: str
    action: str
    skill_id: str | None = None


def parse_selection(text: str, waiting: Sequence[JobView]) -> Selection | None:
    t = (text or "").strip()
    try:
        data = json.loads(t)
    except (ValueError, TypeError):
        data = None
    if data is not None:
        if not isinstance(data, dict):
            return None
        job_id, action, skill = data.get("job_id"), data.get("action"), data.get("skill_id")
        if isinstance(job_id, str) and action in ACTIONS:
            return Selection(job_id, action, skill if isinstance(skill, str) else None)
        return None
    return _from_prose(t, waiting)


def _mentions(text: str, word: str) -> bool:
    return (
        bool(word) and re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.I) is not None
    )


def _picked(job: JobView, t: str) -> str | None:
    """The one skill of this job named in the text (by id or name), else None."""
    names = job.skill_names or ("",) * len(job.skill_ids)
    hits = {sid for sid, name in zip(job.skill_ids, names, strict=True) if _mentions(t, sid)}
    hits |= {sid for sid, name in zip(job.skill_ids, names, strict=True) if _mentions(t, name)}
    return hits.pop() if len(hits) == 1 else None


def _from_prose(t: str, waiting: Sequence[JobView]) -> Selection | None:
    mentioned = [j for j in waiting if j.job_id in t]
    if len(mentioned) > 1:
        return None
    if not mentioned:
        # no job id (typed by a person, or left out by the planner): the newest waiting job
        # whose skill the text names; else the only waiting job
        for job in reversed(waiting):
            if job.state is JobState.AWAITING_SKILL_PICK and (skill := _picked(job, t)):
                return Selection(job.job_id, "pick_skill", skill)
        if len(waiting) != 1:
            return None
        mentioned = list(waiting)
    job = mentioned[0]
    if job.state is JobState.AWAITING_SKILL_PICK:
        skill = _picked(job, t)
        return Selection(job.job_id, "pick_skill", skill) if skill else None
    if job.state is JobState.AWAITING_RUN_CLICK and RUN_WORDS.search(t):
        return Selection(job.job_id, "run_benchmark")
    return None
