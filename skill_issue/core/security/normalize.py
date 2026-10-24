"""SARIF from cisco-ai-skill-scanner → findings in our buckets, deduplicated, with file + line."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from contracts.enums import Bucket, Severity
from core.security.errors import ScannerError

MAX_MESSAGE = 300

CATEGORY_BUCKETS = {
    "prompt_injection": Bucket.PROMPT_INJECTION,
    "unicode_steganography": Bucket.PROMPT_INJECTION,
    "transitive_trust_abuse": Bucket.PROMPT_INJECTION,
    "skill_discovery_abuse": Bucket.PROMPT_INJECTION,
    "autonomy_abuse": Bucket.PROMPT_INJECTION,
    "command_injection": Bucket.DANGEROUS_COMMAND,
    "malware": Bucket.DANGEROUS_COMMAND,
    "obfuscation": Bucket.DANGEROUS_COMMAND,
    "tool_chaining_abuse": Bucket.DANGEROUS_COMMAND,
    "resource_abuse": Bucket.DANGEROUS_COMMAND,
    "data_exfiltration": Bucket.NETWORK,
    "supply_chain_attack": Bucket.INSTALL_PERSISTENCE,
}
# categories too broad to bucket alone; the rule id decides
RULE_HINTS = (
    ("PERSIST", Bucket.INSTALL_PERSISTENCE),
    ("INSTALL", Bucket.INSTALL_PERSISTENCE),
    ("NETWORK", Bucket.NETWORK),
    ("EXFIL", Bucket.NETWORK),
    ("COMMAND", Bucket.DANGEROUS_COMMAND),
    ("SHELL", Bucket.DANGEROUS_COMMAND),
)
LEVEL_SEVERITY = {"error": Severity.HIGH, "warning": Severity.MEDIUM, "note": Severity.LOW}


@dataclass(frozen=True)
class NormFinding:
    bucket: Bucket
    severity: Severity
    file: str  # repo-relative posix path
    line: int  # 1 when the scanner reports a file-level finding
    message: str
    rule_id: str
    source: str


def _bucket(category: str, rule_id: str) -> Bucket:
    if category in CATEGORY_BUCKETS:
        return CATEGORY_BUCKETS[category]
    for hint, bucket in RULE_HINTS:
        if hint in rule_id.upper():
            return bucket
    return Bucket.OTHER


def _severity(props: dict, level: str | None) -> Severity:
    try:
        return Severity(str(props.get("severity", "")).upper())
    except ValueError:
        return LEVEL_SEVERITY.get(level or "", Severity.LOW)


def normalize_sarif(sarif: dict, skill_folder: str) -> list[NormFinding]:
    """skill_folder: repo-relative folder of the scanned SKILL.md ('.' for the repo root)."""
    try:
        results = [r for run in sarif["runs"] for r in run.get("results", [])]
    except (KeyError, TypeError, AttributeError) as ex:
        raise ScannerError("crash", "scanner output is not valid SARIF") from ex
    base = PurePosixPath(skill_folder)
    seen, out = set(), []
    for r in results:
        if not isinstance(r, dict):
            raise ScannerError("crash", "scanner output is not valid SARIF")
        props = r.get("properties") or {}
        rule_id = str(r.get("ruleId") or "UNKNOWN")
        loc = ((r.get("locations") or [{}])[0] or {}).get("physicalLocation") or {}
        uri = (loc.get("artifactLocation") or {}).get("uri") or "SKILL.md"
        line = (loc.get("region") or {}).get("startLine") or 1
        file = str(base / PurePosixPath(uri.removeprefix("./"))).removeprefix("./")
        finding = NormFinding(
            bucket=_bucket(str(props.get("category", "")), rule_id),
            severity=_severity(props, r.get("level")),
            file=file,
            line=int(line),
            message=" ".join(str((r.get("message") or {}).get("text") or rule_id).split())[
                :MAX_MESSAGE
            ],
            rule_id=rule_id,
            source="skill-scanner",
        )
        key = (finding.rule_id, finding.file, finding.line, finding.message)
        if key not in seen:
            seen.add(key)
            out.append(finding)
    return out
