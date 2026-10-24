"""Agent Chat Protocol on the orchestrator. Thin: ack → core.chat.route → act → one reply."""

import time
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

    async def _on_chat(self, ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(
            sender,
            ChatAcknowledgement(timestamp=datetime.now(UTC), acknowledged_msg_id=msg.msg_id),
        )
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
        await ctx.send(to, chat_message(reply))
        self.router.sent(to, reply.text, self.clock())
        emit(
            "orchestrator",
            "chat_reply",
            job.job_id if job else None,
            to=to,
            card=reply.card_kind or "text",
        )
