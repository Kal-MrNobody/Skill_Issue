"""GitHub as an archive source: resolve a ref to a commit, download the tarball at that commit.

The token (optional) is only ever sent to api.github.com and never logged or put in errors.
"""

import re
from pathlib import Path

import httpx

from contracts.enums import ErrorCode
from core.intake.errors import IntakeError
from core.intake.url import RepoRef

API = "https://api.github.com"
SHA = re.compile(r"^[0-9a-f]{40}$")
CHUNK = 1 << 16


class GitHubSource:
    def __init__(
        self, token: str | None = None, client: httpx.Client | None = None, timeout=30.0
    ) -> None:
        self._token = token or None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "skillaudit-intake",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def resolve(self, ref: RepoRef) -> str:
        url = f"{API}/repos/{ref.owner}/{ref.repo}/commits/{ref.ref or 'HEAD'}"
        try:
            resp = self._client.get(url, headers=self._headers("application/vnd.github.sha"))
        except httpx.HTTPError as ex:
            raise IntakeError(ErrorCode.INTERNAL, "Could not reach GitHub", retryable=True) from ex
        _raise_for(resp, ref)
        sha = resp.text.strip()
        if not SHA.match(sha):
            raise IntakeError(ErrorCode.INTERNAL, "GitHub returned an unexpected commit id")
        return sha

    def fetch_archive(self, ref: RepoRef, sha: str, dest: Path, max_bytes: int) -> Path:
        if not SHA.match(sha):
            raise ValueError("archives are only downloaded at a pinned 40-char commit")
        url = f"{API}/repos/{ref.owner}/{ref.repo}/tarball/{sha}"
        try:
            with self._client.stream(
                "GET", url, headers=self._headers("application/vnd.github+json")
            ) as resp:
                _raise_for(resp, ref)
                declared = resp.headers.get("content-length")
                if declared and int(declared) > max_bytes:
                    raise IntakeError(ErrorCode.TOO_LARGE, "Repository is too large to audit")
                written = 0
                with open(dest, "wb") as out:
                    for chunk in resp.iter_bytes(CHUNK):
                        written += len(chunk)
                        if written > max_bytes:
                            raise IntakeError(
                                ErrorCode.TOO_LARGE, "Repository is too large to audit"
                            )
                        out.write(chunk)
        except IntakeError:
            dest.unlink(missing_ok=True)
            raise
        except httpx.HTTPError as ex:
            dest.unlink(missing_ok=True)
            raise IntakeError(ErrorCode.INTERNAL, "Download from GitHub failed", True) from ex
        return dest


def _raise_for(resp: httpx.Response, ref: RepoRef) -> None:
    status = resp.status_code
    if status == 200:
        return
    if status in (404, 422):
        raise IntakeError(
            ErrorCode.REPO_NOT_FOUND,
            f"Couldn't find {ref.display}"
            + (f" at {ref.ref}" if ref.ref else "")
            + ". Check the link; private repositories are not supported.",
        )
    if status == 429 or (status == 403 and resp.headers.get("x-ratelimit-remaining") == "0"):
        raise IntakeError(ErrorCode.RATE_LIMITED, "GitHub rate limit reached, try again later")
    if status == 401:
        raise IntakeError(ErrorCode.INTERNAL, "GitHub rejected the configured token")
    if status == 403:
        raise IntakeError(ErrorCode.PRIVATE_REPO, f"GitHub refused access to {ref.display}")
    raise IntakeError(ErrorCode.INTERNAL, f"GitHub returned HTTP {status}", retryable=True)
