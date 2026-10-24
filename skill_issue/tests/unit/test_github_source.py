"""GitHubSource against a mocked transport: no real network."""

import httpx
import pytest

from agents.sources import GitHubSource
from contracts.enums import ErrorCode
from core.intake.errors import IntakeError
from core.intake.url import RepoRef

SHA = "0123456789abcdef0123456789abcdef01234567"
REF = RepoRef("acme", "skill")


def _source(handler, token=None) -> GitHubSource:
    return GitHubSource(token=token, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_resolve_default_branch_and_auth_header():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, text=SHA + "\n")

    assert _source(handler, token="FAKE-NOT-A-KEY").resolve(REF) == SHA
    assert seen["url"] == "https://api.github.com/repos/acme/skill/commits/HEAD"
    assert seen["auth"] == "Bearer FAKE-NOT-A-KEY"


def test_resolve_explicit_ref_and_no_token():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        return httpx.Response(200, text=SHA)

    _source(handler).resolve(RepoRef("acme", "skill", ref="v1.0"))
    assert seen["url"].endswith("/commits/v1.0") and seen["auth"] is None


@pytest.mark.parametrize(
    "status,headers,code",
    [
        (404, {}, ErrorCode.REPO_NOT_FOUND),
        (422, {}, ErrorCode.REPO_NOT_FOUND),
        (403, {"x-ratelimit-remaining": "0"}, ErrorCode.RATE_LIMITED),
        (429, {}, ErrorCode.RATE_LIMITED),
        (403, {}, ErrorCode.PRIVATE_REPO),
        (500, {}, ErrorCode.INTERNAL),
    ],
)
def test_resolve_error_mapping(status, headers, code):
    src = _source(lambda req: httpx.Response(status, headers=headers, text="nope"))
    with pytest.raises(IntakeError) as exc:
        src.resolve(REF)
    assert exc.value.code is code
    assert "FAKE" not in exc.value.detail


def test_resolve_rejects_non_sha_body():
    with pytest.raises(IntakeError) as exc:
        _source(lambda req: httpx.Response(200, text="<html>")).resolve(REF)
    assert exc.value.code is ErrorCode.INTERNAL


def test_fetch_archive_streams_to_file(tmp_path):
    def handler(req):
        assert str(req.url) == f"https://api.github.com/repos/acme/skill/tarball/{SHA}"
        return httpx.Response(200, content=b"tarbytes")

    path = _source(handler).fetch_archive(REF, SHA, tmp_path / "a.tgz", max_bytes=100)
    assert path.read_bytes() == b"tarbytes"


def test_fetch_archive_refuses_declared_oversize(tmp_path):
    src = _source(lambda req: httpx.Response(200, headers={"content-length": "5000"}, content=b"x"))
    with pytest.raises(IntakeError) as exc:
        src.fetch_archive(REF, SHA, tmp_path / "a.tgz", max_bytes=100)
    assert exc.value.code is ErrorCode.TOO_LARGE


def test_fetch_archive_stops_streaming_past_cap(tmp_path):
    src = _source(lambda req: httpx.Response(200, content=b"x" * 500))
    with pytest.raises(IntakeError) as exc:
        src.fetch_archive(REF, SHA, tmp_path / "a.tgz", max_bytes=100)
    assert exc.value.code is ErrorCode.TOO_LARGE
    assert not (tmp_path / "a.tgz").exists()


def test_fetch_archive_rejects_unpinned_sha(tmp_path):
    with pytest.raises(ValueError):
        _source(lambda req: httpx.Response(200)).fetch_archive(REF, "main", tmp_path / "a", 10)
