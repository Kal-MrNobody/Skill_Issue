"""Find SKILL.md files in a snapshot and parse their frontmatter. Reads files, runs nothing."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

MAX_FILES_LISTED = 200


@dataclass
class SkillInfo:
    skill_id: str
    path: str  # posix path of SKILL.md relative to the repo root
    name: str
    description: str
    files: list[str] = field(default_factory=list)  # other files in the skill folder


def skill_id(path: str) -> str:
    """Stable per SKILL.md path, so the same skill keeps its id across runs and commits."""
    return "skl_" + hashlib.sha1(path.encode()).hexdigest()[:8]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                meta = yaml.safe_load("".join(lines[1:i])) or {}
            except yaml.YAMLError:
                return {}, text
            return (meta if isinstance(meta, dict) else {}), "".join(lines[i + 1 :])
    return {}, text


def find_skills(root: Path, files: list[str], subpath: str | None = None):
    """Return (skills sorted by path, warnings). `files` are the snapshot's extracted files."""
    prefix = f"{subpath.strip('/')}/" if subpath else ""
    skill_paths = sorted(
        f for f in files if PurePosixPath(f).name == "SKILL.md" and f.startswith(prefix)
    )
    dirs = [str(PurePosixPath(p).parent) for p in skill_paths]
    skills, warnings = [], []
    for path, folder in zip(skill_paths, dirs, strict=True):
        meta, _body = parse_frontmatter((root / path).read_text(encoding="utf-8", errors="replace"))
        name = str(meta.get("name") or "").strip()
        desc = " ".join(str(meta.get("description") or "").split())
        if not name or not desc:
            warnings.append(f"{path}: frontmatter is missing name or description")
        if not name:
            name = PurePosixPath(folder).name if folder != "." else "skill"
        skills.append(
            SkillInfo(skill_id(path), path, name, desc, _own_files(path, folder, dirs, files))
        )
    return skills, warnings


def _own_files(path: str, folder: str, all_dirs: list[str], files: list[str]) -> list[str]:
    base = "" if folder == "." else f"{folder}/"
    nested = [f"{d}/" for d in all_dirs if d != folder and (d + "/").startswith(base)]
    own = [
        f[len(base) :]
        for f in files
        if f.startswith(base) and f != path and not any(f.startswith(n) for n in nested)
    ]
    return sorted(own)[:MAX_FILES_LISTED]
