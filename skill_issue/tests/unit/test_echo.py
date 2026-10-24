"""T4.4 duplicate window, T4.5 echo of our own reply, cooldown, concurrency cap; URL extraction."""

import pytest

from core.chat_text import HELP_TEXT, extract_repo_url
from core.echo import EchoGuard, Verdict

A, B = "user-a", "user-b"


@pytest.fixture
def guard():
    return EchoGuard(duplicate_window=120, cooldown=30, max_active_jobs=2)


def test_t4_4_duplicate_inside_window_dropped(guard):
    assert guard.check(A, "audit https://github.com/acme/x", now=0) is Verdict.ACCEPT
    assert guard.check(A, "audit https://github.com/acme/x", now=5) is Verdict.DUPLICATE
    assert guard.check(A, "  Audit   https://github.com/acme/x ", now=6) is Verdict.DUPLICATE
    assert guard.check(B, "audit https://github.com/acme/x", now=7) is Verdict.ACCEPT


def test_duplicate_outside_window_accepted(guard):
    guard.check(A, "hello", now=0)
    assert guard.check(A, "hello", now=121) is Verdict.ACCEPT


def test_t4_5_our_own_reply_echoed_back_is_ignored(guard):
    reply = "Security scan for markdown-tidy: gate STANDARD, 0 findings at MEDIUM or above."
    guard.record_reply(A, reply, now=0)
    assert guard.check(A, reply, now=3) is Verdict.ECHO
    assert guard.check(A, f"Sure! {reply}", now=4) is Verdict.ECHO  # lightly rewritten
    assert guard.check(B, reply, now=5) is Verdict.ACCEPT  # other users are not echoes


def test_emoji_heavy_rewrite_is_treated_as_echo(guard):
    assert guard.check(A, "🚀 Great news ✅ your audit 🎉 is ready", now=0) is Verdict.ECHO


def test_cooldown_between_new_jobs(guard):
    assert guard.may_start_job(A, active_jobs=0, now=0) is Verdict.ACCEPT
    guard.job_started(A, now=0)
    assert guard.may_start_job(A, active_jobs=1, now=10) is Verdict.COOLDOWN
    assert guard.may_start_job(A, active_jobs=1, now=31) is Verdict.ACCEPT
    assert guard.may_start_job(B, active_jobs=0, now=10) is Verdict.ACCEPT


def test_concurrent_job_cap(guard):
    assert guard.may_start_job(A, active_jobs=2, now=1000) is Verdict.TOO_MANY


def test_memory_is_bounded():
    g = EchoGuard(duplicate_window=120, cooldown=30, max_active_jobs=2, max_senders=3)
    for i in range(10):
        g.check(f"s{i}", "x", now=i)
    assert len(g._seen) <= 3


URL = "https://github.com/acme/skill"
TREE = "https://github.com/acme/skill/tree/main/pdf"


@pytest.mark.parametrize(
    "text,expected",
    [
        (f"is this skill safe? {URL}", URL),
        (f"check <{TREE}>.", TREE),
        ("github.com/acme/skill please", "github.com/acme/skill"),
        (f"audit [this]({URL})", URL),
        (f"{URL}.", URL),
        ("no link here", None),
        ("https://gitlab.com/acme/skill", None),
    ],
)
def test_extract_repo_url(text, expected):
    assert extract_repo_url(text, dev_mode=False) == expected


def test_fixture_paths_only_in_dev_mode():
    text = "please audit tests/fixtures/F2_multi"
    assert extract_repo_url(text, dev_mode=False) is None
    assert extract_repo_url(text, dev_mode=True) == "./tests/fixtures/F2_multi"
    assert extract_repo_url("/abs/tests/fixtures/F1_benign", dev_mode=True) == (
        "/abs/tests/fixtures/F1_benign"
    )


def test_help_text_has_an_example():
    assert "https://github.com/" in HELP_TEXT
