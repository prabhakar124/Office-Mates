"""Run a Python tool (ruff, mypy, ...) from the backend's own virtual environment.

Used by the pre-commit hooks so they work the same from a terminal, from the git hook
and on Windows/Linux/macOS, whichever ``python`` happens to be first on PATH:

    python scripts/backend_tool.py ruff check .

Standard library only. Requires ``uv sync`` to have been run in apps/backend.
"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "apps" / "backend"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: backend_tool.py <module> [args...]", file=sys.stderr)
        return 2

    candidates = [
        BACKEND / ".venv" / "Scripts" / "python.exe",  # Windows
        BACKEND / ".venv" / "bin" / "python",  # Linux / macOS
    ]
    python = next((p for p in candidates if p.is_file()), None)
    if python is None:
        print(
            "Backend environment not found. Run `uv sync` in apps/backend first.",
            file=sys.stderr,
        )
        return 1

    return subprocess.run([str(python), "-m", *argv], cwd=BACKEND, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
