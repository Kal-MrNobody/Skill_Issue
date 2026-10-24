"""Run agents in-process (local dispatch, no network) and tear them down cleanly.

uagents' own Agent/Bureau.run_async cancel *every* task in the event loop on shutdown, which
kills the caller too. `running()` starts the same internals via the public `setup()` and stops
only the tasks that belong to our agents.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any, Protocol

import uagents.agent
import uagents.resolver
from uagents import Agent
from uagents.dispatch import dispatcher
from uagents_core.registration import AgentRegistrationPolicy


class NoRegistration(AgentRegistrationPolicy):
    """Local agents are reached through the in-process dispatcher, never via the Almanac."""

    async def register(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def local_agent_kw() -> dict[str, Any]:
    """Local agents: no registration, telemetry, published details or inspector link."""
    return {
        "registration_policy": NoRegistration(),
        "report_events": False,
        "publish_agent_details": False,
        "enable_agent_inspector": False,
        "mark_inactive_on_shutdown": False,
        # never pass log_level: uagents then resets *every* logger in the process to it
    }


def local_agent(name: str, seed: str) -> Agent:
    agent = Agent(name=name, seed=seed, **local_agent_kw())
    logging.getLogger(name).setLevel(logging.WARNING)  # uagents' per-agent logger only
    return agent


class App(Protocol):
    agent: Agent
    tasks: set[asyncio.Task]


async def _no_status_update(*_args: Any, **_kwargs: Any) -> None:
    return None


def go_offline(setter: Callable[[Any, str, Any], None] = setattr) -> None:
    """Local and test runs only. Without this, every Agent() makes blocking gRPC calls to the
    Fetch ledger and every startup posts a status update to the public Almanac API."""
    setter(uagents.agent, "update_agent_status", _no_status_update)
    setter(uagents.agent, "get_almanac_contract", lambda *_a, **_k: None)
    setter(uagents.resolver, "get_almanac_contract", lambda *_a, **_k: None)


def _agent_tasks(agent: Agent) -> list[asyncio.Task]:
    tasks = [
        getattr(agent, "_dispenser_task", None),
        getattr(agent, "_message_queue_task", None),
        getattr(agent, "_registration_task", None),
        *getattr(agent, "_interval_tasks", ()),
        *getattr(agent, "_message_tasks", ()),
    ]
    return [t for t in tasks if t is not None]


@asynccontextmanager
async def running(apps: Iterable[App]):
    apps = list(apps)
    loop = asyncio.get_running_loop()
    for app in apps:
        app.agent.update_loop(loop)
        app.agent.setup()
    try:
        yield apps
    finally:
        pending: list[asyncio.Task] = []
        for app in apps:
            pending += [*app.tasks, *_agent_tasks(app.agent)]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for app in apps:
            dispatcher.unregister(app.agent.address, app.agent)
