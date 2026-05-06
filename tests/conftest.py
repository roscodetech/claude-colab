"""Pytest fixtures.

Critical: redirect ~/.claude-colab to a tmp dir for the duration of each test
so we never read or write the real user config / token.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "claude-colab"
    fake_home.mkdir()

    # Reload paths.py with a patched HOME so all derived paths follow.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import paths

    monkeypatch.setattr(paths, "HOME", fake_home)
    monkeypatch.setattr(paths, "VENV_DIR", fake_home / ".venv")
    monkeypatch.setattr(paths, "CONFIG_PATH", fake_home / "config.json")
    monkeypatch.setattr(paths, "DRIVE_TOKEN_PATH", fake_home / "drive_token.json")
    monkeypatch.setattr(paths, "DRIVE_CREDENTIALS_PATH", fake_home / "drive_credentials.json")
    monkeypatch.setattr(paths, "BROWSER_PROFILE_DIR", fake_home / "chrome-profile")
    monkeypatch.setattr(paths, "RUNS_DIR", fake_home / "runs")
    monkeypatch.setattr(paths, "LOCK_PATH", fake_home / "colab.lock")
    monkeypatch.setattr(paths, "LOG_PATH", fake_home / "claude-colab.log")

    # config caches nothing on import, so no reload needed there.
    yield fake_home
