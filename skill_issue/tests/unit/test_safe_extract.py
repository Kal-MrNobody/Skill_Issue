"""Safe archive extraction (shared by every worker) and the snapshot cache. T2.4, T2.5."""

import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from contracts.enums import ErrorCode
from core.archive import Limits, fetch_snapshot, safe_extract
from core.intake.errors import IntakeError
from core.intake.local_source import LocalSource

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _tar(members: list[tuple[tarfile.TarInfo, bytes | None]], top="repo-abc") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for info, data in members:
            if top and not info.name.startswith("/"):
                info.name = f"{top}/{info.name}"
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


def _file(name: str, data: bytes = b"hi\n", mode: int = 0o755) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    return info, data


def _link(name: str, target: str, kind=tarfile.SYMTYPE) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info, None


def _write(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "a.tar.gz"
    p.write_bytes(data)
    return p


def test_extracts_regular_files_without_top_dir_and_without_exec_bits(tmp_path):
    archive = _write(tmp_path, _tar([_file("SKILL.md"), _file("scripts/run.sh")]))
    dest = tmp_path / "out"
    result = safe_extract(archive, dest, Limits())
    assert sorted(result.files) == ["SKILL.md", "scripts/run.sh"]
    mode = (dest / "scripts/run.sh").stat().st_mode
    assert not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    assert result.warnings == []


@pytest.mark.parametrize(
    "member",
    [_link("hostname", "/etc/hostname"), _link("escape", "../../outside")],
    ids=["absolute-symlink", "escaping-symlink"],
)
def test_t2_4_symlinks_refused_with_warning(tmp_path, member):
    archive = _write(tmp_path, _tar([_file("SKILL.md"), member]))
    dest = tmp_path / "out"
    result = safe_extract(archive, dest, Limits())
    assert result.files == ["SKILL.md"]
    assert any("link" in w and member[0].name.split("/")[-1] in w for w in result.warnings)
    assert not os.path.lexists(dest / member[0].name.split("/")[-1])


def test_t2_4_hardlink_refused(tmp_path):
    archive = _write(tmp_path, _tar([_file("SKILL.md"), _link("hl", "SKILL.md", tarfile.LNKTYPE)]))
    result = safe_extract(archive, tmp_path / "out", Limits())
    assert result.files == ["SKILL.md"] and any("hl" in w for w in result.warnings)


@pytest.mark.parametrize("name", ["/etc/evil", "repo-abc/../../evil", "repo-abc/a/../../../evil"])
def test_path_traversal_rejects_archive(tmp_path, name):
    info, data = _file("x")
    info.name = name
    archive = _write(tmp_path, _tar([_file("SKILL.md"), (info, data)], top=""))
    dest = tmp_path / "deep" / "out"
    with pytest.raises(IntakeError) as exc:
        safe_extract(archive, dest, Limits())
    assert exc.value.code is ErrorCode.UNSAFE_ARCHIVE
    assert not (tmp_path / "evil").exists() and not (tmp_path / "deep" / "evil").exists()


def test_device_and_fifo_members_skipped(tmp_path):
    fifo = tarfile.TarInfo("pipe")
    fifo.type = tarfile.FIFOTYPE
    archive = _write(tmp_path, _tar([_file("SKILL.md"), (fifo, None)]))
    result = safe_extract(archive, tmp_path / "out", Limits())
    assert result.files == ["SKILL.md"] and any("pipe" in w for w in result.warnings)


def test_large_file_skipped_with_warning(tmp_path):
    archive = _write(tmp_path, _tar([_file("SKILL.md"), _file("model.bin", b"\0" * 2048)]))
    result = safe_extract(archive, tmp_path / "out", Limits(max_file_bytes=1024))
    assert result.files == ["SKILL.md"] and any("model.bin" in w for w in result.warnings)


def test_t2_5_oversize_rejected_before_anything_is_written(tmp_path):
    # F9: generated at test time; zeros compress to almost nothing
    members = [_file("SKILL.md")] + [_file(f"blob{i}.bin", b"\0" * 400_000) for i in range(5)]
    archive = _write(tmp_path, _tar(members))
    assert archive.stat().st_size < 50_000
    dest = tmp_path / "out"
    with pytest.raises(IntakeError) as exc:
        safe_extract(archive, dest, Limits(max_total_bytes=1_000_000, max_file_bytes=10**7))
    assert exc.value.code is ErrorCode.TOO_LARGE
    assert not dest.exists()


def test_too_many_files_rejected(tmp_path):
    archive = _write(tmp_path, _tar([_file(f"f{i}") for i in range(30)]))
    with pytest.raises(IntakeError) as exc:
        safe_extract(archive, tmp_path / "out", Limits(max_files=20))
    assert exc.value.code is ErrorCode.TOO_LARGE


def test_compressed_archive_cap(tmp_path):
    archive = _write(tmp_path, os.urandom(5000))
    with pytest.raises(IntakeError) as exc:
        safe_extract(archive, tmp_path / "out", Limits(max_archive_bytes=1000))
    assert exc.value.code is ErrorCode.TOO_LARGE


def test_not_a_tar_is_unsafe(tmp_path):
    archive = _write(tmp_path, b"definitely not a tarball")
    with pytest.raises(IntakeError) as exc:
        safe_extract(archive, tmp_path / "out", Limits())
    assert exc.value.code is ErrorCode.UNSAFE_ARCHIVE


def test_t2_4_f8_fixture_through_local_source(tmp_path):
    source = LocalSource(roots=[FIXTURES])
    ref = source.ref_for(str(FIXTURES / "F8_symlink"))
    sha = source.resolve(ref)
    snap = fetch_snapshot(source, ref, sha, tmp_path / "cache", Limits())
    assert sorted(snap.files) == ["FIXTURE.md", "SKILL.md"]
    assert {w.split(":")[0] for w in snap.warnings} >= {
        "refused link hostname",
        "refused link escape",
    }
    for p in snap.root.rglob("*"):
        assert not p.is_symlink()
    assert not (tmp_path / "outside").exists()
    assert all(p.resolve().is_relative_to(tmp_path) for p in (tmp_path / "cache").rglob("*"))


def test_snapshot_cache_reuses_extraction(tmp_path):
    source = LocalSource(roots=[FIXTURES])
    ref = source.ref_for(str(FIXTURES / "F1_benign"))
    sha = source.resolve(ref)
    first = fetch_snapshot(source, ref, sha, tmp_path / "cache", Limits())
    source.fetch_archive = None  # a cache hit must not download again
    second = fetch_snapshot(source, ref, sha, tmp_path / "cache", Limits())
    assert first.root == second.root and second.files == first.files
    assert first.from_cache is False and second.from_cache is True
