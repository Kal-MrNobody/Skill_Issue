"""Fixture folders as repos (tests and dev mode only). Same archive path as GitHub."""

import hashlib
import io
import os
import tarfile
from pathlib import Path

from contracts.enums import ErrorCode
from core.intake.errors import IntakeError
from core.intake.url import RepoRef


class LocalSource:
    def __init__(self, roots: list[Path]) -> None:
        self.roots = [Path(r).resolve() for r in roots]

    def ref_for(self, path: str) -> RepoRef:
        folder = Path(path).expanduser().resolve()
        if not folder.is_dir() or not any(folder.is_relative_to(r) for r in self.roots):
            raise IntakeError(ErrorCode.BAD_URL, "Local paths are only allowed for fixtures")
        return RepoRef("local", folder.name, local_dir=str(folder))

    def resolve(self, ref: RepoRef) -> str:
        """A content hash stands in for the commit SHA (40 hex chars, stable per content)."""
        h = hashlib.sha1()
        root = Path(ref.local_dir)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            for name in sorted(
                filenames + [d for d in dirnames if os.path.islink(Path(dirpath, d))]
            ):
                p = Path(dirpath, name)
                h.update(str(p.relative_to(root)).encode() + b"\0")
                if p.is_symlink():
                    h.update(b"L" + os.readlink(p).encode())
                else:
                    h.update(b"F" + p.read_bytes())
        return h.hexdigest()

    def fetch_archive(self, ref: RepoRef, sha: str, dest: Path, max_bytes: int) -> Path:
        if self.resolve(ref) != sha:
            raise IntakeError(ErrorCode.INTERNAL, "Local fixture changed after it was pinned")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(ref.local_dir, arcname=ref.repo, recursive=True)  # links stay links
        if buf.tell() > max_bytes:
            raise IntakeError(ErrorCode.TOO_LARGE, "Repository is too large to audit")
        dest.write_bytes(buf.getvalue())
        return dest
