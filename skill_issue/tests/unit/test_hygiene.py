"""T0.5 lint, secrets and boundary checks over the files git would commit."""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]

KEY_PATTERNS = {
    "openai/anthropic key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "aws access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    "github fine-grained token": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "filled secret variable": re.compile(
        r"^\s*(export\s+)?[A-Z][A-Z0-9_]*(SEED|KEY|TOKEN|SECRET|PASSWORD)=[^\s#]+", re.M
    ),
    "slack token": re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "hex seed": re.compile(r"(?<![0-9a-f:])[0-9a-f]{64}(?![0-9a-f])"),
}


def _committable() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p and (ROOT / p).is_file()]


def test_ruff_check_and_format():
    for args in (["check", "."], ["format", "--check", "."]):
        res = subprocess.run(
            [sys.executable, "-m", "ruff", *args], cwd=ROOT, capture_output=True, text=True
        )
        assert res.returncode == 0, res.stdout + res.stderr


def test_no_key_like_strings_in_tracked_files():
    hits = []
    for path in _committable():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pat in KEY_PATTERNS.items():
            if pat.search(text):
                hits.append(f"{path.relative_to(ROOT)}: {label}")
    assert hits == []


def test_env_is_ignored_and_example_has_no_values():
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert ignored.returncode == 0
    example = (ROOT / ".env.example").read_text()
    assignments = [ln for ln in example.splitlines() if ln and not ln.startswith("#")]
    assert assignments
    # report variable names only, so a failure never echoes a secret value
    filled = [ln.split("=", 1)[0] for ln in assignments if not ln.endswith("=")]
    assert filled == []


@pytest.mark.parametrize(
    "var",
    [
        "ORCHESTRATOR_SEED",
        "INTAKE_SEED",
        "SECURITY_SEED",
        "BENCHMARK_SEED",
        "REPORT_SEED",
        "AGENTVERSE_API_KEY",
        "MODEL_BASE_URL",
        "MODEL_API_KEY",
        "MODEL_ID",
        "GITHUB_TOKEN",
    ],
)
def test_env_example_lists_variable(var):
    assert re.search(rf"^{var}=", (ROOT / ".env.example").read_text(), re.M)


def test_core_does_not_import_uagents():
    code = (
        "import pkgutil, importlib, sys, core\n"
        "for mod in pkgutil.walk_packages(core.__path__, 'core.'):\n"
        "    importlib.import_module(mod.name)\n"
        "assert not any(n.split('.')[0] in ('uagents', 'uagents_core') for n in sys.modules)\n"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_models_defined_only_in_contracts():
    offenders = []
    for path in _committable():
        rel = path.relative_to(ROOT)
        if path.suffix != ".py" or rel.parts[0] in ("contracts", "tests"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                bases = {getattr(b, "id", getattr(b, "attr", None)) for b in node.bases}
                if bases & {"Model", "BaseModel"}:
                    offenders.append(f"{rel}:{node.lineno} {node.name}")
    assert offenders == []
