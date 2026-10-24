"""A local stand-in for ASI:One: chat with the orchestrator, print every card, click through.

    uv run python -m scripts.fake_asi1 tests/fixtures/F2_multi --mode prose
    uv run python -m scripts.fake_asi1 https://github.com/owner/repo --mode json

Adapted from the cards doc's plain-Python client, but in-process (local dispatch, no
Agentverse): real intake and security, stub benchmark and report. --mode json sends the
selection object as JSON text (a direct @mention); --mode prose sends a sentence like the
ASI:One planner writes.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    MetadataContent,
    TextContent,
    chat_protocol_spec,
)

from agents.config import cache_root, load_dotenv
from agents.runtime import go_offline, local_agent, running
from agents.security.scanner import CliScanner
from agents.sources import GitHubSource
from agents.system import System, build_system
from core.archive import Limits
from core.chat import ChatRouter
from core.flow import FlowConfig
from core.intake.local_source import LocalSource
from core.intake.pipeline import IntakeDeps
from core.security.pipeline import ScanDeps

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"
DEV_SEED_PREFIX = "skillaudit-fake-asi1-dev"  # not a secret: local runs only


@dataclass
class Received:
    text: str
    card_kind: str | None
    payload: dict | None
    terminal: bool
    session: str = ""


class FakeAsi1:
    def __init__(self, seed: str) -> None:
        self.agent = local_agent("fake_asi1", seed)
        self.tasks: set[asyncio.Task] = set()
        self.inbox: asyncio.Queue[Received] = asyncio.Queue()
        self.outbox: list[tuple[str, str]] = []
        self.sent_sessions: list[str] = []  # session of each message we sent, in order
        self.acks = 0
        proto = Protocol(spec=chat_protocol_spec)
        proto.on_message(ChatMessage)(self._on_chat)
        proto.on_message(ChatAcknowledgement)(self._on_ack)
        self.agent.include(proto)
        self.agent.on_interval(period=0.05)(self._flush)

    async def _flush(self, ctx: Context) -> None:
        """uagents only sends from handlers, so say() queues and this interval sends."""
        while self.outbox:
            to, text = self.outbox.pop(0)
            self.sent_sessions.append(str(ctx.session))
            await ctx.send(to, ChatMessage(content=[TextContent(text=text)]))

    async def _on_chat(self, ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        meta = next((c.metadata for c in msg.content if isinstance(c, MetadataContent)), {})
        payload = json.loads(meta["card_payload"]) if meta.get("card_payload") else None
        terminal = meta.get("is_terminal") == "true"
        received = Received(msg.text(), meta.get("card_kind"), payload, terminal, str(ctx.session))
        await self.inbox.put(received)

    async def _on_ack(self, ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        self.acks += 1

    async def say(self, to: str, text: str) -> None:
        self.outbox.append((to, text))

    async def next_reply(self, timeout: float) -> Received:
        return await asyncio.wait_for(self.inbox.get(), timeout)


def primary_selection(r: Received) -> dict | None:
    if r.terminal or not r.payload:
        return None
    if r.card_kind == "carousel":
        return r.payload["items"][0]["primary_cta"]["selection"]
    if r.card_kind == "detail":
        ctas = r.payload["ctas"]
        return next((c for c in ctas if c.get("primary")), ctas[0])["selection"]
    return None


def as_prose(sel: dict) -> str:
    if sel["action"] == "pick_skill":
        return f"The user picked skill {sel['skill_id']} for job {sel['job_id']}."
    return f"The user clicked Run benchmark for job {sel['job_id']} and wants to start it."


def click_text(sel: dict, mode: str) -> str:
    return json.dumps(sel) if mode == "json" else as_prose(sel)


async def converse(
    client: FakeAsi1, to: str, target: str, mode: str, timeout: float = 120, show=print
) -> list[Received]:
    """Send the link, then keep clicking the primary button until a card needs no input."""
    seen: list[Received] = []
    await client.say(to, f"Can you audit this skill? {target}")
    while True:
        r = await client.next_reply(timeout)
        seen.append(r)
        show(r)
        sel = primary_selection(r)
        if sel is None:
            return seen
        await client.say(to, click_text(sel, mode))


def build_chat_system(seed_prefix: str, cache: Path, real_scan: bool = True, **kw) -> System:
    local = LocalSource(roots=[FIXTURES])
    github = GitHubSource(token=os.environ.get("GITHUB_TOKEN"))
    intake = IntakeDeps(github=github, local=local, cache_root=cache / "intake", limits=Limits())
    scan = ScanDeps(github, local, cache / "scan", CliScanner(), Limits()) if real_scan else None
    return build_system(
        seed_prefix,
        intake_deps=intake,
        scan_deps=scan,
        router=ChatRouter(dev_mode=True),
        **kw,
    )


def _show(r: Received) -> None:
    print("\n── reply " + "─" * 60)
    print(r.text)
    if r.card_kind:
        print(f"[card: {r.card_kind}{' · terminal' if r.terminal else ''}]")
        print(json.dumps(r.payload, indent=2)[:4000])


async def _main(target: str, mode: str) -> int:
    system = build_chat_system(DEV_SEED_PREFIX, cache_root(), cfg=FlowConfig(), tick=0.2)
    client = FakeAsi1(f"{DEV_SEED_PREFIX}-client")
    async with running([*system.apps, client]):
        seen = await converse(client, system.orchestrator.agent.address, target, mode, show=_show)
    final = seen[-1]
    print(f"\n{len(seen)} replies, final card: {final.card_kind or 'text only'}")
    return 0 if final.terminal else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", help="GitHub URL or tests/fixtures/<name>")
    parser.add_argument("--mode", choices=["json", "prose"], default="json")
    args = parser.parse_args()
    load_dotenv()
    go_offline()
    logging.getLogger("skillaudit").setLevel(logging.WARNING)
    target = args.target
    if not target.startswith(("http", "github.com", "/", "./")):
        target = "./" + target
    return asyncio.run(_main(target, args.mode))


if __name__ == "__main__":
    sys.exit(main())
