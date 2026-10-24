"""Run SkillAudit for ASI:One: the orchestrator as an Agentverse mailbox agent, workers in-process.

    uv run python -m scripts.run_mailbox [--port 8000] [--no-connect]

Pre-step-7 deployment: one process. Only the orchestrator is registered (mailbox, Chat
Protocol manifest, README); the four workers are local agents reachable only through it.
Intake and the security scan are real; there is no benchmark yet, so every report is
security-only. Seeds and keys come from .env and are never printed.

On startup it connects the mailbox through the agent's own /connect endpoint (what the
Inspector's Connect → Mailbox button does) using AGENTVERSE_API_KEY. --no-connect skips that,
so you can connect from the printed Inspector link instead.

Hosting (Render): the agent's REST port (inspector, /connect) must never be public, so when
PORT is set a separate health server answers on it, and the agent keeps its private port.
With RENDER_EXTERNAL_URL set it pings itself every few minutes, because a mailbox agent gets
no inbound traffic and Render's free tier sleeps after 15 idle minutes.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx
from uagents import Agent

from agents.config import cache_root, load_dotenv
from agents.runtime import running
from agents.security.scanner import CliScanner
from agents.sources import GitHubSource
from agents.system import build_system
from core.archive import Limits
from core.chat import ChatRouter
from core.flow import FlowConfig
from core.intake.pipeline import IntakeDeps
from core.security.pipeline import ScanDeps

NAME = "SkillAudit"
README = Path(__file__).parents[1] / "agents" / "orchestrator" / "README.md"
ROLES = ("intake", "security", "benchmark", "report")


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is not set (see .env.example)")
    return value


async def _connect(port: int, token: str) -> None:
    await asyncio.sleep(3)  # let the REST server come up
    url = f"http://127.0.0.1:{port}/connect"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json={"user_token": token, "agent_type": "mailbox"})
        body = resp.json()
        ok = resp.status_code == 200 and body.get("success")
        print(
            f"[skillaudit] mailbox connect: {'ok' if ok else 'FAILED'} {body.get('detail') or ''}"
        )
    except (httpx.HTTPError, ValueError) as ex:
        print(f"[skillaudit] mailbox connect FAILED: {type(ex).__name__}")


KEEPALIVE_SECONDS = 600


async def _health(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Answers anything with 200 ok. Exposes nothing about the agent."""
    try:
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        pass
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
    try:
        await writer.drain()
    finally:
        writer.close()


async def _keepalive(url: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            await asyncio.sleep(KEEPALIVE_SECONDS)
            try:
                await client.get(f"{url.rstrip('/')}/health")
            except httpx.HTTPError as ex:
                print(f"[skillaudit] keepalive failed: {type(ex).__name__}")


async def _main(port: int, connect: bool) -> None:
    loop = asyncio.get_running_loop()
    background: list[asyncio.Task] = []
    if public_port := os.environ.get("PORT"):
        if int(public_port) == port:
            raise SystemExit("PORT must differ from the agent's private --port")
        server = await asyncio.start_server(_health, "0.0.0.0", int(public_port))
        print(f"[skillaudit] health server on :{public_port}")
        background.append(loop.create_task(server.serve_forever()))
    if external := os.environ.get("RENDER_EXTERNAL_URL"):
        background.append(loop.create_task(_keepalive(external)))
    orchestrator = Agent(
        name=NAME,
        seed=_env("ORCHESTRATOR_SEED"),
        port=port,
        mailbox=True,
        readme_path=str(README),
        publish_agent_details=True,
        description="Checks an AI agent skill (GitHub repo with SKILL.md) before you install it.",
    )
    github = GitHubSource(token=os.environ.get("GITHUB_TOKEN"))
    cache = cache_root()
    system = build_system(
        "unused",
        cfg=FlowConfig(suite_id=None),  # no benchmark yet → security-only report
        tick=1.0,
        intake_deps=IntakeDeps(github=github, local=None, cache_root=cache / "intake"),
        scan_deps=ScanDeps(github, None, cache / "scan", CliScanner(), Limits()),
        router=ChatRouter(dev_mode=False),
        orchestrator_agent=orchestrator,
        worker_seeds={role: _env(f"{role.upper()}_SEED") for role in ROLES},
    )
    print(f"[skillaudit] {NAME} address: {orchestrator.address}")
    if connect:
        background.append(loop.create_task(_connect(port, _env("AGENTVERSE_API_KEY"))))
    async with running(system.workers.values()):
        await orchestrator.run_async()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-connect", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    for name in ("skillaudit", NAME):
        logging.getLogger(name).setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger("skillaudit").addHandler(handler)
    logging.getLogger("skillaudit").propagate = False
    asyncio.run(_main(args.port, not args.no_connect))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
