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


def _from_prose(t: str, waiting: Sequence[JobView]) -> Selection | None:
    mentioned = [j for j in waiting if j.job_id in t]
    if len(mentioned) == 1:
        job = mentioned[0]
    elif not mentioned and len(waiting) == 1:
        job = waiting[0]  # the planner may leave out the id when only one job is waiting
    else:
        return None
    if job.state is JobState.AWAITING_SKILL_PICK:
        ids = [s for s in job.skill_ids if re.search(rf"(?<![\w-]){re.escape(s)}(?![\w-])", t)]
        return Selection(job.job_id, "pick_skill", ids[0]) if len(ids) == 1 else None
    if job.state is JobState.AWAITING_RUN_CLICK and RUN_WORDS.search(t):
        return Selection(job.job_id, "run_benchmark")
    return None
