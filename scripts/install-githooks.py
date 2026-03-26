#!/usr/bin/env python3
"""Install git hooks for this repository.

Usage:
    python scripts/install-githooks.py

Installs a pre-commit hook that runs ruff (lint + format check) and pytest.
If either step fails the commit is aborted.
"""

import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / ".git" / "hooks"
PRE_COMMIT_PATH = HOOKS_DIR / "pre-commit"

PRE_COMMIT_SCRIPT = """\
#!/bin/sh
# Pre-commit hook — installed by scripts/install-githooks.py
set -e

echo "--- pre-commit: ruff check ---"
uv run ruff check .
uv run ruff format --check .

echo "--- pre-commit: pytest ---"
uv run pytest tests/ -q

echo "--- pre-commit: all checks passed ---"
"""


def main() -> int:
    if not HOOKS_DIR.is_dir():
        print(f"error: hooks directory not found: {HOOKS_DIR}", file=sys.stderr)
        print("Are you running this from inside a git repository?", file=sys.stderr)
        return 1

    if PRE_COMMIT_PATH.exists():
        print(f"Replacing existing pre-commit hook: {PRE_COMMIT_PATH}")
    else:
        print(f"Installing pre-commit hook: {PRE_COMMIT_PATH}")

    PRE_COMMIT_PATH.write_text(PRE_COMMIT_SCRIPT)

    # Make the hook executable (rwxr-xr-x)
    current = stat.S_IMODE(PRE_COMMIT_PATH.stat().st_mode)
    PRE_COMMIT_PATH.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print("Done. The following checks will run before every commit:")
    print("  1. ruff check .")
    print("  2. ruff format --check .")
    print("  3. pytest tests/ -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
