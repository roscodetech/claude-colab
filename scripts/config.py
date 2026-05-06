"""Config file read/write. All settings live in ~/.claude-colab/config.json."""

from __future__ import annotations

import json
from typing import Any

from . import paths as _paths
from .paths import ensure_home

DEFAULTS: dict[str, Any] = {
    "drive_scope_folder": "claude-colab",
    "drive_scope_full": False,
    "save_images": True,
    "image_dir": "~/.claude-colab/runs",
    "debugger_max_retries": 2,
    "browser_profile_dir": "~/.claude-colab/chrome-profile",
    "default_runtime": "cpu",
    "headed": True,
}


def load() -> dict[str, Any]:
    """Load config, falling back to defaults for any missing keys."""
    ensure_home()
    if not _paths.CONFIG_PATH.exists():
        return dict(DEFAULTS)
    with _paths.CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Merge with defaults so new keys added in updates don't crash on old configs.
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save(cfg: dict[str, Any]) -> None:
    ensure_home()
    with _paths.CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def update(**kwargs: Any) -> dict[str, Any]:
    """Patch one or more keys and persist. Returns the new full config."""
    cfg = load()
    cfg.update(kwargs)
    save(cfg)
    return cfg


def reset() -> dict[str, Any]:
    """Restore defaults. Used by `colab-init --reset`."""
    cfg = dict(DEFAULTS)
    save(cfg)
    return cfg
