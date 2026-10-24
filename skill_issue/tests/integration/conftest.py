import json
import logging
import uuid

import pytest

from agents.runtime import go_offline
from agents.system import System, build_system


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Agents must not touch the Fetch ledger or the public Almanac API from tests."""
    go_offline(monkeypatch.setattr)


@pytest.fixture
def system_factory():
    def make(**kw) -> System:
        return build_system(seed_prefix=f"test-{uuid.uuid4().hex}", **kw)

    return make


@pytest.fixture
def events(caplog):
    caplog.set_level(logging.INFO, logger="skillaudit")

    def read() -> list[dict]:
        return [json.loads(r.getMessage()) for r in caplog.records if r.name == "skillaudit"]

    return read
