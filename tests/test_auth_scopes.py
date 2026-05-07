"""OAuth scope expansion — config field, scope resolution, token clearing."""

from __future__ import annotations

import pytest

from scripts import auth, config, paths


def test_default_scope_is_file():
    assert auth.get_scopes() == ["https://www.googleapis.com/auth/drive.file"]


def test_scope_full_returns_drive_scope():
    config.update(oauth_scope="full")
    assert auth.get_scopes() == ["https://www.googleapis.com/auth/drive"]


def test_set_oauth_scope_persists_in_config():
    auth.set_oauth_scope("full")
    assert config.load()["oauth_scope"] == "full"
    auth.set_oauth_scope("file")
    assert config.load()["oauth_scope"] == "file"


def test_set_oauth_scope_clears_existing_token():
    # Pre-write a fake token file so we can verify it gets cleaned up.
    paths.DRIVE_TOKEN_PATH.write_text('{"refresh_token": "old"}', encoding="utf-8")
    assert paths.DRIVE_TOKEN_PATH.exists()

    auth.set_oauth_scope("full")
    # Wider scope can't be granted via token refresh — must re-auth.
    assert not paths.DRIVE_TOKEN_PATH.exists()


def test_set_oauth_scope_rejects_unknown():
    with pytest.raises(ValueError, match="unknown oauth_scope"):
        auth.set_oauth_scope("readonly")
    with pytest.raises(ValueError):
        auth.set_oauth_scope("")


def test_set_oauth_scope_returns_full_config():
    cfg = auth.set_oauth_scope("full")
    assert cfg["oauth_scope"] == "full"
    # Other defaults still present (forward-compat).
    assert "save_images" in cfg


def test_scopes_match_helper():
    """_scopes_match returns True iff target scopes are subset of token scopes."""

    class _Creds:
        def __init__(self, scopes):
            self.scopes = scopes

    target_file = ["https://www.googleapis.com/auth/drive.file"]
    target_full = ["https://www.googleapis.com/auth/drive"]

    # Token with file scope satisfies file-scope request.
    assert auth._scopes_match(_Creds(target_file), target_file)
    # Token with file scope does NOT satisfy full-scope request.
    assert not auth._scopes_match(_Creds(target_file), target_full)
    # Token with full scope DOES satisfy a file-scope request? No — drive.file
    # and drive are separate scope strings. Subset check sees them as different.
    assert not auth._scopes_match(_Creds(target_full), target_file)
