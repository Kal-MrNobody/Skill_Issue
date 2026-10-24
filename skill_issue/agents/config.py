"""Configuration from the environment. Secrets are read here and never logged."""

import os
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Fill os.environ from a .env file without overriding variables that are already set."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def cache_root() -> Path:
    return Path(os.environ.get("SKILLAUDIT_CACHE", Path.home() / ".cache" / "skillaudit"))
