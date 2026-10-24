"""Safe download + extraction of a repo snapshot. Shared by every worker (CLAUDE.md rule 4, 12).

Nothing in a snapshot is ever executed or imported on the host. Extraction refuses links,
absolute and '..' paths and special files, checks size and count caps from the tar headers
before writing anything, skips large files and never sets exec bits.
"""

import json
import os
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from contracts.enums import ErrorCode
from core.intake.errors import IntakeError
from core.intake.url import RepoRef

CHUNK = 1 << 16


@dataclass(frozen=True)
class Limits:
    max_archive_bytes: int = 50 * 1024 * 1024  # compressed download
    max_total_bytes: int = 100 * 1024 * 1024  # sum of declared file sizes
    max_files: int = 5000
    max_file_bytes: int = 5 * 1024 * 1024  # larger files are skipped (binaries, models)


@dataclass
class ExtractResult:
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    root: Path
    files: list[str]
    warnings: list[str]
    from_cache: bool


class ArchiveSource(Protocol):
    def resolve(self, ref: RepoRef) -> str: ...
    def fetch_archive(self, ref: RepoRef, sha: str, dest: Path, max_bytes: int) -> Path: ...


def _too_large(what: str) -> IntakeError:
    return IntakeError(ErrorCode.TOO_LARGE, f"Repository is too large to audit ({what})")


def _unsafe(why: str) -> IntakeError:
    return IntakeError(ErrorCode.UNSAFE_ARCHIVE, f"Refused the repository archive: {why}")


def _relative_names(members: list[tarfile.TarInfo]) -> list[str]:
    """Strip the single top-level folder GitHub (and LocalSource) put in archives."""
    names = [m.name for m in members]
    firsts = {n.split("/", 1)[0] for n in names}
    strip = (
        len(firsts) == 1
        and not names[0].startswith("/")
        and all("/" in n or m.isdir() for m, n in zip(members, names, strict=True))
    )
    out = []
    for m, n in zip(members, names, strict=True):
        if strip:
            n = n.split("/", 1)[1] if "/" in n else ""
        out.append(n.rstrip("/") if m.isdir() else n)
    return out


def _check_name(raw: str, rel: str) -> None:
    p = PurePosixPath(raw)
    if raw.startswith("/") or p.is_absolute() or re.match(r"^[A-Za-z]:", raw):
        raise _unsafe(f"absolute path {raw!r}")
    if ".." in p.parts or "\\" in raw or "\0" in raw:
        raise _unsafe(f"path escapes the repository: {raw!r}")


def safe_extract(archive: Path, dest: Path, limits: Limits) -> ExtractResult:
    if archive.stat().st_size > limits.max_archive_bytes:
        raise _too_large(f"archive over {limits.max_archive_bytes} bytes")
    try:
        tar = tarfile.open(archive, mode="r:*")
    except (tarfile.TarError, EOFError, OSError) as ex:
        raise _unsafe("not a valid tar archive") from ex
    with tar:
        try:
            members = tar.getmembers()
        except (tarfile.TarError, EOFError, OSError) as ex:
            raise _unsafe("corrupt tar archive") from ex
        rels = _relative_names(members) if members else []
        for m, rel in zip(members, rels, strict=True):
            _check_name(m.name, rel)
        if len(members) > limits.max_files:
            raise _too_large(f"{len(members)} entries, limit {limits.max_files}")
        total = sum(m.size for m in members if m.isreg())
        if total > limits.max_total_bytes:
            raise _too_large(f"{total} bytes unpacked, limit {limits.max_total_bytes}")

        result = ExtractResult()
        dest.mkdir(parents=True, exist_ok=False)
        root = dest.resolve()
        try:
            for m, rel in zip(members, rels, strict=True):
                if not rel:
                    continue
                if m.issym() or m.islnk():
                    kind = "symlink" if m.issym() else "hardlink"
                    result.warnings.append(f"refused link {rel}: {kind} -> {m.linkname}")
                    continue
                target = (root / rel).resolve()
                if not target.is_relative_to(root):
                    raise _unsafe(f"path escapes the repository: {m.name!r}")
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not m.isreg():
                    result.warnings.append(f"skipped {rel}: special file")
                    continue
                if m.size > limits.max_file_bytes:
                    result.warnings.append(f"skipped {rel}: {m.size} bytes is over the file cap")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                with src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, CHUNK)
                os.chmod(target, 0o644)
                result.files.append(rel)
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
    result.files.sort()
    return result


def _cache_key(ref: RepoRef, sha: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", f"{ref.owner}__{ref.repo}__{sha}")


def fetch_snapshot(
    source: ArchiveSource, ref: RepoRef, sha: str, cache_root: Path, limits: Limits
) -> Snapshot:
    """The one way any worker gets repo files: by (repo, pinned commit), cached by commit."""
    cache_root.mkdir(parents=True, exist_ok=True)
    final = cache_root / _cache_key(ref, sha)
    meta = final / "meta.json"
    if meta.is_file():
        data = json.loads(meta.read_text())
        return Snapshot(final / "tree", data["files"], data["warnings"], from_cache=True)

    work = Path(tempfile.mkdtemp(prefix="dl-", dir=cache_root))
    try:
        archive = source.fetch_archive(ref, sha, work / "archive.tar.gz", limits.max_archive_bytes)
        result = safe_extract(archive, work / "tree", limits)
        archive.unlink()
        (work / "meta.json").write_text(
            json.dumps({"files": result.files, "warnings": result.warnings})
        )
        try:
            os.rename(work, final)
        except OSError:  # another request finished first; use its copy
            shutil.rmtree(work, ignore_errors=True)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return Snapshot(final / "tree", result.files, result.warnings, from_cache=False)
