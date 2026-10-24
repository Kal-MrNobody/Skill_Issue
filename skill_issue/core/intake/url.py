"""GitHub URL → RepoRef. Anything that is not a plain github.com repo URL is BAD_URL."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from contracts.enums import ErrorCode
from core.intake.errors import IntakeError

NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})$")
HINT = "Send a GitHub repo link like https://github.com/owner/repo"


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str
    ref: str | None = None  # branch, tag or commit from /tree/<ref>; None → default branch
    path: str | None = None  # sub-folder from /tree/<ref>/<path>
    local_dir: str | None = None  # LocalSource only (fixtures, dev mode)

    @property
    def display(self) -> str:
        if self.local_dir:
            return f"local:{self.repo}"
        return f"github.com/{self.owner}/{self.repo}"


def _bad(why: str) -> IntakeError:
    return IntakeError(ErrorCode.BAD_URL, f"{why}. {HINT}")


def parse_github_url(url: str) -> RepoRef:
    url = (url or "").strip()
    if not url or any(c.isspace() for c in url):
        raise _bad("That doesn't look like a link")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise _bad("Only http(s) GitHub links are supported")
    if parts.username or parts.password or parts.port:
        raise _bad("GitHub links must not contain credentials or a port")
    if (parts.hostname or "").lower() not in ("github.com", "www.github.com"):
        raise _bad("Only github.com repositories are supported")

    segs = [s for s in parts.path.split("/") if s]
    if len(segs) < 2:
        raise _bad("The link needs both an owner and a repository")
    owner, repo = segs[0], segs[1].removesuffix(".git")
    if not NAME.match(owner) or not NAME.match(repo) or ".." in (owner, repo):
        raise _bad("Owner or repository name looks invalid")

    rest = segs[2:]
    if not rest:
        return RepoRef(owner, repo)
    if rest[0] != "tree" or len(rest) < 2:
        raise _bad("Link to the repository or a folder (/tree/...), not a single file")
    ref, sub = rest[1], rest[2:]
    if any(s in (".", "..") for s in [ref, *sub]):
        raise _bad("Folder paths must not contain '.' or '..'")
    return RepoRef(owner, repo, ref=ref, path="/".join(sub) or None)
