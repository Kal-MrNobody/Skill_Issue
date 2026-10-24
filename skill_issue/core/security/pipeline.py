"""Security scan: snapshot (shared safe download) → scanner → normalize → domains → gate."""

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from contracts.enums import ErrorCode, GateDecision
from core.archive import ArchiveSource, Limits, fetch_snapshot
from core.intake.local_source import LocalSource
from core.intake.pipeline import IntakeDeps, source_for
from core.intake.skills import parse_frontmatter
from core.security.domains import DomainRef, domain_inventory
from core.security.errors import ScannerError
from core.security.gate import gate_for
from core.security.normalize import NormFinding, normalize_sarif

__all__ = ["ScanDeps", "ScanOutcome", "Scanner", "ScannerError", "run_scan"]


class Scanner(Protocol):
    version: str

    def scan(self, skill_dir: Path) -> dict: ...


@dataclass
class ScanDeps:
    github: ArchiveSource | None
    local: LocalSource | None
    cache_root: Path
    scanner: Scanner
    limits: Limits = field(default_factory=Limits)


@dataclass
class ScanOutcome:
    findings: list[NormFinding]
    domains: list[str]
    undeclared_domains: list[str]
    domain_refs: list[DomainRef]
    gate: GateDecision
    scan_error: ErrorCode | None
    scan_error_detail: str
    scanner_version: str


def run_scan(repo_url: str, commit_sha: str, skill_path: str, deps: ScanDeps) -> ScanOutcome:
    """Raises IntakeError if the snapshot can't be fetched; scanner trouble fails safe instead."""
    lookup = IntakeDeps(deps.github, deps.local, deps.cache_root, deps.limits)
    source, ref = source_for(repo_url, lookup)
    snap = fetch_snapshot(source, ref, commit_sha, deps.cache_root, deps.limits)

    folder = str(PurePosixPath(skill_path).parent)
    base = "" if folder == "." else f"{folder}/"
    skill_dir = snap.root / folder
    own_files = [f[len(base) :] for f in snap.files if f.startswith(base)]
    meta, _ = parse_frontmatter((snap.root / skill_path).read_text(errors="replace"))
    refs = domain_inventory(skill_dir, own_files, str(meta.get("description") or ""))

    error, detail, findings = None, "", []
    try:
        findings = normalize_sarif(deps.scanner.scan(skill_dir), folder)
    except ScannerError as ex:
        error, detail = ErrorCode.SCAN_FAILED, f"scanner {ex.kind}: {ex.detail}"
    return ScanOutcome(
        findings=findings,
        domains=[d.domain for d in refs],
        undeclared_domains=[d.domain for d in refs if d.undeclared],
        domain_refs=refs,
        gate=gate_for(findings, scan_failed=error is not None),
        scan_error=error,
        scan_error_detail=detail,
        scanner_version=deps.scanner.version,
    )
