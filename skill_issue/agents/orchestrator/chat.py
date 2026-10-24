"""Agent Chat Protocol on the orchestrator. Thin: ack → core.chat.route → act → one reply."""

import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    TextContent,
    chat_protocol_spec,
)

from agents.common import emit
from core.cards import Reply, card_metadata, reply_for
from core.chat import ChatRouter, Drop, Say, Select, StartJob
from core.jobs import Job

MAX_SESSIONS = 10_000


def chat_message(reply: Reply) -> ChatMessage:
    content: list = [TextContent(text=reply.text)]
    if reply.card_kind and reply.payload is not None:
        content.append(MetadataContent(metadata=card_metadata(reply)))
    return ChatMessage(timestamp=datetime.now(UTC), msg_id=uuid4(), content=content)


class ChatLayer:
    def __init__(
        self, app, router: ChatRouter, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.app = app
        self.router = router
        self.clock = clock
        self.protocol = Protocol(spec=chat_protocol_spec)
        self.protocol.on_message(ChatMessage)(self._on_chat)
        self.protocol.on_message(ChatAcknowledgement)(self._on_ack)
        # sender -> context of their latest ChatMessage. Replies sent later (after a worker
        # hop) must go out in the user's chat session under the chat protocol: Agentverse
        # chat rejects anything else with HTTP 500.
        self._chat_ctx: OrderedDict[str, Context] = OrderedDict()

    async def _on_chat(self, ctx: Context, sender: str, msg: ChatMessage) -> None:
        ack = ChatAcknowledgement(timestamp=datetime.now(UTC), acknowledged_msg_id=msg.msg_id)
        self._chat_ctx[sender] = ctx
        self._chat_ctx.move_to_end(sender)
        while len(self._chat_ctx) > MAX_SESSIONS:
            self._chat_ctx.popitem(last=False)
        status = await ctx.send(sender, ack)
        emit("orchestrator", "chat_ack", None, to=sender, delivery=_delivery(status))
        text = msg.text().strip()
        if not text:  # start/end session, metadata only
            if any(isinstance(c, EndSessionContent) for c in msg.content):
                emit("orchestrator", "chat_end_session", None, sender=sender)
            return
        jobs = self.app.jobs_of(sender)
        action = self.router.route(sender, text, jobs, self.clock())
        emit("orchestrator", "chat", None, sender=sender, action=type(action).__name__)
        if isinstance(action, Drop):
            emit("orchestrator", "dropped", None, reason=action.reason, sender=sender)
        elif isinstance(action, Say):
            await self.say(ctx, sender, action.reply)
        elif isinstance(action, StartJob):
            self.app.submit(action.repo_url, owner=sender)
        elif isinstance(action, Select):
            job = self.app.store.get(action.job_id)
            if action.action == "pick_skill":
                await self.app.pick_skill(ctx, job, action.skill_path)
            else:
                await self.app.click_run(ctx, job)

    async def _on_ack(self, ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        return None

    async def notify(self, ctx: Context, job: Job, kind: str) -> None:
        if job.owner:
            await self.say(ctx, job.owner, reply_for(job, kind, k=self.app.flow.cfg.k), job)

    async def say(self, ctx: Context, to: str, reply: Reply, job: Job | None = None) -> None:
        ctx = self._chat_ctx.get(to, ctx)
        status = await ctx.send(to, chat_message(reply))
        delivery = _delivery(status)
        job_id = job.job_id if job else None
        emit(
            "orchestrator",
            "chat_reply",
            job_id,
            to=to,
            card=reply.card_kind or "text",
            delivery=delivery,
        )
        if reply.card_kind and delivery not in ("delivered", "sent"):
            # some chat clients (Agentverse's test chat) reject card messages outright:
            # the same reply as plain text still answers the user
            status = await ctx.send(to, chat_message(Reply(reply.text)))
            emit(
                "orchestrator",
                "chat_reply",
                job_id,
                to=to,
                card="text-fallback",
                delivery=_delivery(status),
            )
        self.router.sent(to, reply.text, self.clock())


def _delivery(status) -> str:
    """MsgStatus → 'delivered' / 'failed: <detail>' for the log (no message content)."""
    value = str(getattr(getattr(status, "status", None), "value", status))
    detail = getattr(status, "detail", "") or ""
    return value if value in ("delivered", "sent") else f"{value}: {detail}"[:200]
