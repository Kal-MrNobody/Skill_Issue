# SkillAudit: orchestrator (Agentverse mailbox) + in-process workers.
# Scanned repos are only downloaded and statically scanned here, never executed.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    PYTHONUNBUFFERED=1 \
    SKILLAUDIT_CACHE=/tmp/skillaudit

# the static scanner, isolated in its own tool venv (version pinned in agents/security/scanner.py)
RUN uv tool install cisco-ai-skill-scanner==2.2.2

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agents ./agents
COPY contracts ./contracts
COPY core ./core
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 app
USER app

# PORT (set by Render) serves only a health check; the agent's own port 8000 stays private
CMD ["/app/.venv/bin/python", "-m", "scripts.run_mailbox", "--port", "8000"]
