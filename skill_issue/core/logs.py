"""One structured log line per event. Callers pass ids and counts only, never secrets."""

import json
from typing import Any


def log_line(agent: str, event: str, job_id: str | None = None, **fields: Any) -> str:
    return json.dumps({"agent": agent, "event": event, "job_id": job_id, **fields}, default=str)
