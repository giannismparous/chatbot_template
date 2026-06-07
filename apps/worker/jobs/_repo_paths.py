from __future__ import annotations

from pathlib import Path

from packages.core.stack.factory import project_root


def resolve_repo_path(path: str | Path) -> Path:
    """Resolve a repo-relative path against chatbot_template root (not CWD or apps/)."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root() / candidate).resolve()
