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
