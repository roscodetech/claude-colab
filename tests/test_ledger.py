"""Active-runtime ledger: read, write, sweep, cap enforcement.

Ledger lives at ~/.claude-colab/active_runtimes.json and tracks runtimes
the plugin has spawned. Used to enforce a configurable cap (default 2)
under Pro+'s ~3-concurrent-session limit.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from scripts import ledger, paths


@pytest.fixture
def patched_ledger_path(tmp_path, monkeypatch):
    p = tmp_path / "active_runtimes.json"
    monkeypatch.setattr(paths, "LEDGER_PATH", p)
    return p


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _iso_offset(hours: int) -> str:
    t = datetime.now(UTC) + timedelta(hours=hours)
    return t.isoformat().replace("+00:00", "Z")


# ---------- read() ----------


def test_read_missing_file_returns_empty(patched_ledger_path):
    assert ledger.read() == []


def test_read_corrupt_json_returns_empty(patched_ledger_path):
    patched_ledger_path.write_text("not json{[", encoding="utf-8")
    assert ledger.read() == []


def test_read_non_list_root_returns_empty(patched_ledger_path):
    patched_ledger_path.write_text('{"oops": "object"}', encoding="utf-8")
    assert ledger.read() == []


def test_read_drops_entries_missing_required_fields(patched_ledger_path):
    patched_ledger_path.write_text(
        json.dumps(
            [
                {"notebook_id": "good", "started_at": _iso_now()},
                {"notebook_id": "no_timestamp"},
                {"started_at": _iso_now()},
                "not a dict",
                None,
            ]
        ),
        encoding="utf-8",
    )
    entries = ledger.read()
    assert len(entries) == 1
    assert entries[0]["notebook_id"] == "good"


def test_read_excludes_stale_entries(patched_ledger_path):
    patched_ledger_path.write_text(
        json.dumps(
            [
                {"notebook_id": "fresh", "started_at": _iso_now()},
                {"notebook_id": "stale", "started_at": _iso_offset(hours=-25)},
            ]
        ),
        encoding="utf-8",
    )
    entries = ledger.read()
    assert [e["notebook_id"] for e in entries] == ["fresh"]


# ---------- add() ----------


def test_add_appends_entry(patched_ledger_path):
    entry = ledger.add("nb1", runtime_type="cpu", pid=1234)
    assert entry["notebook_id"] == "nb1"
    assert entry["runtime_type"] == "cpu"
    assert entry["pid"] == 1234
    assert "started_at" in entry

    entries = ledger.read()
    assert len(entries) == 1
    assert entries[0]["notebook_id"] == "nb1"


def test_add_pid_defaults_to_current_process(patched_ledger_path, monkeypatch):
    monkeypatch.setattr("scripts.ledger.os.getpid", lambda: 99999)
    entry = ledger.add("nb1")
    assert entry["pid"] == 99999


def test_add_replaces_existing_entry_for_same_notebook(patched_ledger_path):
    ledger.add("nb1", runtime_type="cpu")
    ledger.add("nb1", runtime_type="gpu")
    entries = ledger.read()
    assert len(entries) == 1
    assert entries[0]["runtime_type"] == "gpu"


def test_add_persists_iso_z_timestamp(patched_ledger_path):
    ledger.add("nb1")
    raw = json.loads(patched_ledger_path.read_text(encoding="utf-8"))
    assert raw[0]["started_at"].endswith("Z")
    # Must round-trip through fromisoformat after dropping the Z.
    datetime.fromisoformat(raw[0]["started_at"].replace("Z", "+00:00"))


# ---------- remove() ----------


def test_remove_existing_entry(patched_ledger_path):
    ledger.add("nb1")
    ledger.add("nb2")
    assert ledger.remove("nb1") is True
    entries = ledger.read()
    assert [e["notebook_id"] for e in entries] == ["nb2"]


def test_remove_missing_returns_false(patched_ledger_path):
    assert ledger.remove("nonexistent") is False


def test_remove_from_empty_ledger(patched_ledger_path):
    assert ledger.remove("anything") is False


# ---------- sweep() ----------


def test_sweep_drops_stale_and_persists(patched_ledger_path):
    patched_ledger_path.write_text(
        json.dumps(
            [
                {"notebook_id": "fresh", "started_at": _iso_now()},
                {"notebook_id": "stale", "started_at": _iso_offset(hours=-25)},
            ]
        ),
        encoding="utf-8",
    )
    live = ledger.sweep()
    assert [e["notebook_id"] for e in live] == ["fresh"]

    raw = json.loads(patched_ledger_path.read_text(encoding="utf-8"))
    assert len(raw) == 1
    assert raw[0]["notebook_id"] == "fresh"


def test_sweep_noop_when_all_fresh(patched_ledger_path):
    ledger.add("nb1")
    ledger.add("nb2")
    mtime_before = patched_ledger_path.stat().st_mtime_ns
    live = ledger.sweep()
    assert len(live) == 2
    # No rewrite when nothing to sweep — keeps mtime stable.
    assert patched_ledger_path.stat().st_mtime_ns == mtime_before


# ---------- preflight() ----------


def test_preflight_under_cap(patched_ledger_path):
    ledger.add("nb1")
    res = ledger.preflight(cap=2)
    assert res["status"] == "ok"
    assert res["active_count"] == 1
    assert res["cap"] == 2


def test_preflight_at_cap(patched_ledger_path):
    ledger.add("nb1")
    ledger.add("nb2")
    res = ledger.preflight(cap=2)
    assert res["status"] == "rate_limited"
    assert res["active_count"] == 2
    assert res["cap"] == 2
    ids = {e["notebook_id"] for e in res["active"]}
    assert ids == {"nb1", "nb2"}
    assert "nb1" in res["hint"] or "nb2" in res["hint"]


def test_preflight_with_stale_entry_treats_as_free(patched_ledger_path):
    patched_ledger_path.write_text(
        json.dumps(
            [
                {"notebook_id": "fresh", "started_at": _iso_now()},
                {"notebook_id": "stale", "started_at": _iso_offset(hours=-30)},
            ]
        ),
        encoding="utf-8",
    )
    res = ledger.preflight(cap=2)
    assert res["status"] == "ok"
    assert res["active_count"] == 1


def test_preflight_cap_one_allows_zero_active(patched_ledger_path):
    res = ledger.preflight(cap=1)
    assert res["status"] == "ok"


def test_preflight_cap_one_rejects_one_active(patched_ledger_path):
    ledger.add("nb1")
    res = ledger.preflight(cap=1)
    assert res["status"] == "rate_limited"


# ---------- concurrency ----------


def test_concurrent_adds_all_persist(patched_ledger_path):
    """50 threads each add a unique entry; the lock prevents any from being lost."""
    errors = []

    def worker(i):
        try:
            ledger.add(f"nb{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent adds failed: {errors}"
    entries = ledger.read()
    assert {e["notebook_id"] for e in entries} == {f"nb{i}" for i in range(50)}
