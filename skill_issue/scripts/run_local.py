"""Run all five agents in one process and push one fake job through them.

    uv run python -m scripts.run_local [repo_url] [--serve]

Default: run one job with stub workers, print one JSON log line per event, exit when the
job ends. --serve: keep all five agents running in a uagents Bureau until Ctrl+C.
Local mode only: dev seeds, no Almanac/ledger traffic (see agents.runtime.go_offline).
"""

import argparse
import asyncio
import logging
import sys

from uagents import Bureau

from agents.common import StubBehaviour
from agents.runtime import go_offline, running
from agents.system import build_system
from contracts.enums import JobState
from core.flow import FlowConfig

DEV_SEED_PREFIX = "skillaudit-local-dev"  # not a secret: local runs only, never deployed


def _config() -> FlowConfig:
    return FlowConfig(
        deadlines={
            JobState.INTAKE: 10,
            JobState.SCANNING: 10,
            JobState.BENCHMARKING: 5,
            JobState.REPORTING: 10,
        },
        heartbeat_timeout=3,
        auto_pick=True,
        auto_run=True,
    )


async def _run_once(repo_url: str) -> int:
    bench = StubBehaviour(duration=3.0, heartbeat_every=1.0)
    system = build_system(DEV_SEED_PREFIX, cfg=_config(), behaviours={"benchmark": bench})
    async with running(system.apps):
        job_id = system.orchestrator.submit(repo_url)
        job = await system.orchestrator.wait(job_id, timeout=60)
    print(f"\njob {job.job_id}: {job.state}", end="")
    if job.failure:
        print(f" at {job.failure.step} ({job.failure.code})", end="")
    print(f"\npath: {' -> '.join(job.history)}")
    return 0 if job.state is JobState.DONE else 1


def _serve() -> None:
    system = build_system(DEV_SEED_PREFIX, cfg=_config(), tick=1.0)
    for app in system.apps:
        print(f"{app.agent.name:>12}: {app.agent.address}")
    Bureau(agents=[app.agent for app in system.apps], port=8000).run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo_url", nargs="?", default="https://github.com/example/skill")
    parser.add_argument("--serve", action="store_true", help="keep agents up in a Bureau")
    args = parser.parse_args()
    go_offline()
    logging.getLogger("skillaudit").setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger("skillaudit").addHandler(handler)
    logging.getLogger("skillaudit").propagate = False
    if args.serve:
        _serve()
        return 0
    return asyncio.run(_run_once(args.repo_url))


if __name__ == "__main__":
    raise SystemExit(main())
