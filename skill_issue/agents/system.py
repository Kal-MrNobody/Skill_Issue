"""Wire the orchestrator and four workers together for one-process runs."""

from dataclasses import dataclass, field

from uagents import Agent

from agents.benchmark.agent import build as build_benchmark
from agents.common import StubBehaviour, WorkerApp
from agents.intake.agent import build as build_intake
from agents.orchestrator.agent import OrchestratorApp
from agents.report.agent import build as build_report
from agents.security.agent import build as build_security
from core.chat import ChatRouter
from core.flow import FlowConfig
from core.intake.pipeline import IntakeDeps
from core.security.pipeline import ScanDeps

WORKER_BUILDERS = {
    "intake": build_intake,
    "security": build_security,
    "benchmark": build_benchmark,
    "report": build_report,
}


@dataclass
class System:
    orchestrator: OrchestratorApp
    workers: dict[str, WorkerApp] = field(default_factory=dict)

    @property
    def apps(self) -> list:
        return [self.orchestrator, *self.workers.values()]


def build_system(
    seed_prefix: str,
    cfg: FlowConfig | None = None,
    behaviours: dict[str, StubBehaviour] | None = None,
    tick: float = 0.05,
    intake_deps: IntakeDeps | None = None,
    scan_deps: ScanDeps | None = None,
    router: ChatRouter | None = None,
    orchestrator_agent: Agent | None = None,
    worker_seeds: dict[str, str] | None = None,
) -> System:
    """Workers are stubs unless their real dependencies are passed in."""
    behaviours = behaviours or {}
    orch = OrchestratorApp(
        seed=f"{seed_prefix}-orchestrator",
        cfg=cfg,
        tick=tick,
        router=router,
        publish_manifest=orchestrator_agent is not None,
        agent=orchestrator_agent,
    )
    seeds = worker_seeds or {}
    real = {"intake": {"deps": intake_deps}, "security": {"deps": scan_deps}}
    workers = {
        role: build(
            seeds.get(role, f"{seed_prefix}-{role}"),
            orch.agent.address,
            behaviours.get(role),
            **{k: v for k, v in real.get(role, {}).items() if v is not None},
        )
        for role, build in WORKER_BUILDERS.items()
    }
    orch.set_workers({role: w.agent.address for role, w in workers.items()})
    return System(orch, workers)
