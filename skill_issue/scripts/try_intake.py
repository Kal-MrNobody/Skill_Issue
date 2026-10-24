"""Run intake on a GitHub URL or a fixture folder and print the result as JSON.

uv run python -m scripts.try_intake <github-url-or-fixture-path>
"""

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from agents.config import cache_root, load_dotenv
from agents.sources import GitHubSource
from core.intake.errors import IntakeError
from core.intake.local_source import LocalSource
from core.intake.pipeline import IntakeDeps, run_intake

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    load_dotenv()
    target = sys.argv[1]
    if Path(target).is_dir() and not target.startswith(("/", ".")):
        target = "./" + target
    deps = IntakeDeps(
        github=GitHubSource(token=os.environ.get("GITHUB_TOKEN")),
        local=LocalSource(roots=[FIXTURES]),
        cache_root=cache_root() / "intake",
    )
    try:
        out = run_intake(target, None, deps)
    except IntakeError as ex:
        print(json.dumps({"error": str(ex.code), "detail": ex.detail}, indent=2))
        return 1
    result = {
        "repo": out.ref.display,
        "commit_sha": out.commit_sha,
        "candidates": [asdict(c) for c in out.candidates],
        "warnings": out.warnings,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
