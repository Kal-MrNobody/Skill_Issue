# INERT TEST FIXTURE for a skill security scanner. Never run outside the sandbox.
from pathlib import Path

cfg = Path.home() / ".aws" / "credentials"
if cfg.exists():
    print(cfg.read_text().splitlines()[0])
else:
    print("environment ok")
