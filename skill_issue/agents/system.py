"""Wire the orchestrator and four workers together for one-process runs."""

from dataclasses import dataclass, field

from agents.benchmark.agent import build as build_benchmark
from agents.common import StubBehaviour, WorkerApp
from agents.intake.agent import build as build_intake
from agents.orchestrator.agent import OrchestratorApp
from agents.report.agent import build as build_report
from agents.security.agent import build as build_security
from core.flow import FlowConfig

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
) -> System:
    behaviours = behaviours or {}
    orch = OrchestratorApp(seed=f"{seed_prefix}-orchestrator", cfg=cfg, tick=tick)
    workers = {
        role: build(f"{seed_prefix}-{role}", orch.agent.address, behaviours.get(role))
        for role, build in WORKER_BUILDERS.items()
    }
    orch.set_workers({role: w.agent.address for role, w in workers.items()})
    return System(orch, workers)
