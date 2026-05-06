"""Centralized path resolution for claude-colab.

Single source of truth — every other module imports from here so we never
hardcode `~/.claude-colab` in two places.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HOME = Path.home() / ".claude-colab"

VENV_DIR = HOME / ".venv"
CONFIG_PATH = HOME / "config.json"
DRIVE_TOKEN_PATH = HOME / "drive_token.json"
DRIVE_CREDENTIALS_PATH = HOME / "drive_credentials.json"
BROWSER_PROFILE_DIR = HOME / "chrome-profile"
RUNS_DIR = HOME / "runs"
LOCK_PATH = HOME / "colab.lock"
LOG_PATH = HOME / "claude-colab.log"

# Plugin root is two levels up from this file (scripts/paths.py → claude-colab/)
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = PLUGIN_ROOT / "requirements.txt"


def venv_python() -> Path:
    """Path to the python executable inside the bundled venv."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_pip() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def ensure_home() -> None:
    """Create ~/.claude-colab/ and subdirs. Idempotent."""
    HOME.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # Tighten perms on POSIX — token files live here.
    if os.name == "posix":
        os.chmod(HOME, 0o700)
