"""Config persistence + default merging."""

from __future__ import annotations

from scripts import config


def test_load_returns_defaults_when_no_file():
    cfg = config.load()
    assert cfg["drive_scope_folder"] == "claude-colab"
    assert cfg["debugger_max_retries"] == 2
    assert cfg["save_images"] is True


def test_save_then_load_round_trip():
    config.save({"drive_scope_folder": "my-stuff", "debugger_max_retries": 5})
    cfg = config.load()
    assert cfg["drive_scope_folder"] == "my-stuff"
    assert cfg["debugger_max_retries"] == 5
    # New keys in DEFAULTS still appear after save (forward-compat).
    assert "save_images" in cfg


def test_update_patches_only_given_keys():
    config.save(dict(config.DEFAULTS))
    config.update(debugger_max_retries=7)
    cfg = config.load()
    assert cfg["debugger_max_retries"] == 7
    assert cfg["drive_scope_folder"] == "claude-colab"  # untouched


def test_reset_restores_defaults():
    config.save({"debugger_max_retries": 99, "drive_scope_full": True})
    cfg = config.reset()
    assert cfg["debugger_max_retries"] == 2
    assert cfg["drive_scope_full"] is False


def test_load_merges_old_config_with_new_default_keys():
    """Simulate a config from an older plugin version missing new keys."""
    old_config = {"drive_scope_folder": "test", "debugger_max_retries": 3}
    config.save(old_config)
    cfg = config.load()
    # Old keys preserved
    assert cfg["drive_scope_folder"] == "test"
    # Newer default keys filled in
    assert "save_images" in cfg
    assert "default_runtime" in cfg
