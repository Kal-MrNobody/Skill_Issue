"""Run the cisco-ai-skill-scanner CLI on a snapshot folder and return its SARIF.

The scanner only reads files (static + behavioural dataflow analysis); nothing from the
scanned repo is executed. It gets a minimal environment, so none of our secrets reach it.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.security.errors import ScannerError

SCANNER_VERSION = "2.2.2"  # install: uv tool install cisco-ai-skill-scanner==2.2.2
BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
LLM_ENV_PREFIX = "SKILL_SCANNER_LLM_"


def scanner_env(use_llm: bool) -> dict[str, str]:
    env = {k: os.environ[k] for k in BASE_ENV if k in os.environ}
    if use_llm:
        env |= {k: v for k, v in os.environ.items() if k.startswith(LLM_ENV_PREFIX)}
    return env


def default_command() -> list[str]:
    return [os.environ.get("SKILL_SCANNER_BIN") or shutil.which("skill-scanner") or "skill-scanner"]


class CliScanner:
    def __init__(
        self,
        command: list[str] | None = None,
        timeout: float = 120.0,
        use_llm: bool = False,
        version: str = SCANNER_VERSION,
    ) -> None:
        self.command = command or default_command()
        self.timeout = timeout
        self.use_llm = use_llm
        self.version = version

    def scan(self, skill_dir: Path) -> dict:
        with tempfile.TemporaryDirectory(prefix="scan-") as tmp:
            out = Path(tmp) / "result.sarif"
            argv = [*self.command, "scan", ".", "--use-behavioral", "--format", "sarif"]
            if self.use_llm:
                argv.append("--use-llm")
            argv += ["--output", str(out)]
            try:
                proc = subprocess.run(
                    argv,
                    cwd=skill_dir,
                    env=scanner_env(self.use_llm),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as ex:
                raise ScannerError("timeout", f"no result after {self.timeout:.0f}s") from ex
            except OSError as ex:
                raise ScannerError("crash", "scanner could not be started") from ex
            if proc.returncode != 0:
                raise ScannerError("crash", f"scanner exited with code {proc.returncode}")
            try:
                return json.loads(out.read_text())
            except (OSError, ValueError) as ex:
                raise ScannerError("crash", "scanner wrote no valid SARIF") from ex
