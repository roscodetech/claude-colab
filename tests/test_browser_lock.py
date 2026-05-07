"""Verify the file-lock contract (one notebook at a time).

Doesn't actually launch Chromium — just exercises the lock primitive.
"""

from __future__ import annotations

import threading

import pytest

from scripts import browser


def test_acquire_lock_blocks_concurrent_holder():
    """Second acquirer raises ColabBusyError immediately."""
    held = threading.Event()
    release = threading.Event()

    def hold_lock():
        with browser.acquire_lock(timeout=5):
            held.set()
            release.wait()

    t = threading.Thread(target=hold_lock)
    t.start()
    held.wait(timeout=2)

    with pytest.raises(browser.ColabBusyError), browser.acquire_lock(timeout=0.5):
        pytest.fail("should not have acquired")

    release.set()
    t.join()


def test_lock_releases_after_with_block():
    with browser.acquire_lock(timeout=1):
        pass
    # Re-acquire should succeed immediately.
    with browser.acquire_lock(timeout=1):
        pass


# --- _merge_output_text (PR #6: rich-output capture)


def test_merge_returns_parent_when_rich_empty():
    assert browser._merge_output_text("hello\n", "") == "hello"


def test_merge_returns_rich_when_parent_empty():
    assert browser._merge_output_text("", "DataFrame text\n") == "DataFrame text"


def test_merge_dedups_when_rich_is_substring_of_parent():
    """Colab sometimes mirrors stream output into the iframe chrome."""
    parent = "0   1\n1   2\n2   3"
    rich = "0   1"
    assert browser._merge_output_text(parent, rich) == parent


def test_merge_concatenates_when_distinct():
    assert browser._merge_output_text("stdout-only", "df-table-output") == (
        "stdout-only\ndf-table-output"
    )


def test_merge_handles_both_empty():
    assert browser._merge_output_text("", "") == ""
    assert browser._merge_output_text(None, None) == ""
