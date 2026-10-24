"""The scanner subprocess wrapper: argv, environment hygiene, timeout and crash mapping.

These tests run a harmless stand-in program, never the real scanner and never fixture code.
"""

import json
import sys
from pathlib import Path

import pytest

from agents.security.scanner import CliScanner, scanner_env
from core.security.pipeline import ScannerError


def _stub(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "fake_scanner.py"
    script.write_text(body)
    return [sys.executable, "-I", str(script)]


def test_env_passes_no_secrets(monkeypatch):
    for k in ("MODEL_API_KEY", "AGENTVERSE_API_KEY", "GITHUB_TOKEN", "INTAKE_SEED"):
        monkeypatch.setenv(k, "FAKE-NOT-A-KEY")
    monkeypatch.setenv("SKILL_SCANNER_LLM_API_KEY", "FAKE-NOT-A-KEY")
    env = scanner_env(use_llm=False)
    assert "FAKE-NOT-A-KEY" not in env.values()
    assert set(env) <= {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}


def test_env_passes_scanner_llm_settings_only_when_enabled(monkeypatch):
    monkeypatch.setenv("SKILL_SCANNER_LLM_API_KEY", "FAKE-NOT-A-KEY")
    monkeypatch.setenv("MODEL_API_KEY", "FAKE-OTHER")
    env = scanner_env(use_llm=True)
    assert env["SKILL_SCANNER_LLM_API_KEY"] == "FAKE-NOT-A-KEY" and "MODEL_API_KEY" not in env


def test_runs_scan_with_sarif_output_in_skill_dir(tmp_path):
    record = tmp_path / "argv.json"
    body = f"""
import json, os, sys
args = sys.argv[1:]
json.dump({{"args": args, "cwd": os.getcwd()}}, open({str(record)!r}, "w"))
out = args[args.index("--output") + 1]
json.dump({{"runs": [{{"results": []}}]}}, open(out, "w"))
"""
    skill = tmp_path / "skill"
    skill.mkdir()
    scanner = CliScanner(command=_stub(tmp_path, body), timeout=10, version="test")
    assert scanner.scan(skill) == {"runs": [{"results": []}]}
    seen = json.loads(record.read_text())
    assert seen["cwd"] == str(skill)
    assert seen["args"][:4] == ["scan", ".", "--use-behavioral", "--format"]
    assert "--use-llm" not in seen["args"]


def test_timeout_maps_to_scanner_error(tmp_path):
    scanner = CliScanner(command=_stub(tmp_path, "import time; time.sleep(5)"), timeout=0.5)
    with pytest.raises(ScannerError) as exc:
        scanner.scan(tmp_path)
    assert exc.value.kind == "timeout"


@pytest.mark.parametrize(
    "body", ["import sys; sys.exit(3)", "pass", "import sys; open(sys.argv[-1], 'w').write('{')"]
)
def test_crash_or_bad_output_maps_to_scanner_error(tmp_path, body):
    scanner = CliScanner(command=_stub(tmp_path, body), timeout=10)
    with pytest.raises(ScannerError) as exc:
        scanner.scan(tmp_path)
    assert exc.value.kind == "crash"


def test_missing_binary_maps_to_scanner_error(tmp_path):
    scanner = CliScanner(command=["/nonexistent/skill-scanner"], timeout=5)
    with pytest.raises(ScannerError):
        scanner.scan(tmp_path)
