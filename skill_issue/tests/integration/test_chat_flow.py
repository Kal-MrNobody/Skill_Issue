"""Step 4: the user flow over the Agent Chat Protocol, driven by scripts.fake_asi1."""

import asyncio
import json
import uuid

import pytest

from agents.common import StubBehaviour
from agents.runtime import running
from contracts.enums import GateDecision, JobState
from core.cards import iter_selections, validate_card
from core.chat_text import HELP_TEXT
from core.flow import FlowConfig
from scripts.fake_asi1 import FakeAsi1, build_chat_system, click_text, converse, primary_selection

pytestmark = pytest.mark.integration

F1, F2 = "./tests/fixtures/F1_benign", "./tests/fixtures/F2_multi"


def _setup(tmp_path, **kw):
    prefix = f"test-{uuid.uuid4().hex}"
    system = build_chat_system(prefix, tmp_path, real_scan=False, cfg=FlowConfig(), tick=0.05, **kw)
    return system, FakeAsi1(f"{prefix}-client")


def _check_card(r):
    if r.card_kind:
        validate_card(r.card_kind, r.payload)
        for sel in iter_selections(r.card_kind, r.payload):
            assert sel["job_id"] and sel["action"]
    assert r.text.strip()  # every reply carries a useful text block


@pytest.mark.parametrize("mode", ["json", "prose"])
async def test_t4_6_t4_8_f2_picker_then_security_then_report(tmp_path, mode):
    system, client = _setup(tmp_path)
    orch = system.orchestrator.agent.address
    async with running([*system.apps, client]):
        seen = await converse(client, orch, F2, mode, timeout=20, show=lambda r: None)
        await asyncio.sleep(0.3)
        assert client.inbox.empty()  # exactly one reply per user action
    assert [r.card_kind for r in seen] == ["carousel", "detail", "custom"]
    assert seen[-1].terminal
    for r in seen:
        _check_card(r)
    assert client.acks == 3  # every ChatMessage we sent was acknowledged


async def test_t4_7_gate_block_has_no_run_button(tmp_path):
    system, client = _setup(
        tmp_path, behaviours={"security": StubBehaviour(gate=GateDecision.BLOCK)}
    )
    orch = system.orchestrator.agent.address
    async with running([*system.apps, client]):
        seen = await converse(client, orch, F1, "json", timeout=20, show=lambda r: None)
    assert len(seen) == 1 and seen[0].card_kind == "custom" and seen[0].terminal
    assert primary_selection(seen[0]) is None
    assert "run_benchmark" not in json.dumps(seen[0].payload)
    job = system.orchestrator.jobs_of(client.agent.address)[0]
    assert JobState.BENCHMARKING not in job.history and job.bench is None


async def test_t4_9_no_url_gets_one_helpful_reply(tmp_path):
    system, client = _setup(tmp_path)
    async with running([*system.apps, client]):
        await client.say(system.orchestrator.agent.address, "hello, what can you do?")
        r = await client.next_reply(5)
        await asyncio.sleep(0.3)
        assert client.inbox.empty()
    assert r.text == HELP_TEXT and r.card_kind is None


async def test_t4_4_t4_5_duplicates_and_echoes_get_no_reply(tmp_path):
    system, client = _setup(tmp_path)
    orch = system.orchestrator.agent.address
    async with running([*system.apps, client]):
        await client.say(orch, f"audit {F2}")
        await client.say(orch, f"audit {F2}")  # duplicate inside the window
        picker = await client.next_reply(10)
        await client.say(orch, picker.text)  # our own reply sent back to us
        await asyncio.sleep(0.5)
        assert client.inbox.empty()
        assert len(system.orchestrator.jobs_of(client.agent.address)) == 1
        await client.say(orch, click_text(primary_selection(picker), "json"))
        assert (await client.next_reply(10)).card_kind == "detail"


async def test_selection_from_another_sender_cannot_drive_a_job(tmp_path):
    system, client = _setup(tmp_path)
    intruder = FakeAsi1(f"intruder-{uuid.uuid4().hex}")
    orch = system.orchestrator.agent.address
    async with running([*system.apps, client, intruder]):
        await client.say(orch, f"audit {F2}")
        picker = await client.next_reply(10)
        await intruder.say(orch, click_text(primary_selection(picker), "json"))
        stale = await intruder.next_reply(5)
        job = system.orchestrator.jobs_of(client.agent.address)[0]
    assert "no longer active" in stale.text
    assert job.state is JobState.AWAITING_SKILL_PICK
