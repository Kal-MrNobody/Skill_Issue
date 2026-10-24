"""Intake: URL → pinned commit → safe snapshot → skill candidates + claims.

Network access only happens inside the injected source (agents/sources.GitHubSource).
"""

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from contracts.enums import ErrorCode
from core.archive import ArchiveSource, Limits, fetch_snapshot
from core.intake.claims import ClaimExtractor, ClaimRecord, RuleClaimExtractor, is_claim_source
from core.intake.errors import IntakeError
from core.intake.local_source import LocalSource
from core.intake.skills import SkillInfo, find_skills
from core.intake.url import RepoRef, parse_github_url


@dataclass
class IntakeDeps:
    github: ArchiveSource | None
    local: LocalSource | None  # dev/tests only
    cache_root: Path
    limits: Limits = field(default_factory=Limits)
    claims: ClaimExtractor = field(default_factory=RuleClaimExtractor)


@dataclass
class Candidate(SkillInfo):
    claims: list[ClaimRecord] = field(default_factory=list)


@dataclass
class IntakeOutcome:
    ref: RepoRef
    commit_sha: str
    candidates: list[Candidate]
    claims: list[ClaimRecord]
    warnings: list[str]


def _looks_local(repo_url: str) -> bool:
    return repo_url.startswith(("/", "./", "../", "~"))


def source_for(repo_url: str, deps: IntakeDeps) -> tuple[ArchiveSource, RepoRef]:
    if deps.local is not None and _looks_local(repo_url):
        return deps.local, deps.local.ref_for(repo_url)
    ref = parse_github_url(repo_url)
    if deps.github is None:
        raise IntakeError(ErrorCode.INTERNAL, "GitHub access is not configured")
    return deps.github, ref


def run_intake(repo_url: str, ref_override: str | None, deps: IntakeDeps) -> IntakeOutcome:
    source, ref = source_for(repo_url, deps)
    if ref_override and not ref.ref:
        ref = RepoRef(ref.owner, ref.repo, ref_override, ref.path, ref.local_dir)
    sha = source.resolve(ref)
    snap = fetch_snapshot(source, ref, sha, deps.cache_root, deps.limits)
    skills, warnings = find_skills(snap.root, snap.files, ref.path)
    if not skills:
        where = f" under {ref.path}" if ref.path else ""
        raise IntakeError(
            ErrorCode.NO_SKILL,
            f"No SKILL.md found in {ref.display}{where} at commit {sha[:7]}. "
            "A skill repository needs at least one SKILL.md file.",
        )

    claims: list[ClaimRecord] = []
    for f in snap.files:
        if is_claim_source(f):
            text = (snap.root / f).read_text(encoding="utf-8", errors="replace")
            claims += deps.claims.extract(f, text)

    candidates = []
    for s in skills:
        folder = str(PurePosixPath(s.path).parent)
        base = "" if folder == "." else f"{folder}/"
        own = [c for c in claims if c.file.startswith(base)]
        candidates.append(Candidate(**vars(s), claims=own))
    return IntakeOutcome(ref, sha, candidates, claims, snap.warnings + warnings)
