"""Scan one skill folder (fixture or repo snapshot path) with the real scanner and print findings.

uv run python -m scripts.try_scan tests/fixtures/F5_dangerous_shell
"""

import json
import sys
from pathlib import Path

from agents.config import cache_root
from agents.security.scanner import CliScanner
from core.archive import Limits
from core.intake.errors import IntakeError
from core.intake.local_source import LocalSource
from core.security.pipeline import ScanDeps, run_scan

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"


def scan_fixture(path: str) -> dict:
    local = LocalSource(roots=[FIXTURES])
    target = "./" + path if not path.startswith(("/", ".")) else path
    sha = local.resolve(local.ref_for(target))
    deps = ScanDeps(None, local, cache_root() / "scan", CliScanner(), Limits())
    out = run_scan(target, sha, "SKILL.md", deps)
    return {
        "gate": str(out.gate),
        "scan_error": out.scan_error and str(out.scan_error),
        "scanner_version": out.scanner_version,
        "findings": [
            {
                "bucket": str(f.bucket),
                "severity": str(f.severity),
                "where": f"{f.file}:{f.line}",
                "rule": f.rule_id,
                "message": f.message,
            }
            for f in out.findings
        ],
        "domains": [
            {"domain": d.domain, "where": f"{d.file}:{d.line}", "undeclared": d.undeclared}
            for d in out.domain_refs
        ],
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        print(json.dumps(scan_fixture(sys.argv[1]), indent=2))
    except IntakeError as ex:
        print(json.dumps({"error": str(ex.code), "detail": ex.detail}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
