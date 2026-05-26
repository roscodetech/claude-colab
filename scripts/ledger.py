"""Active-runtime ledger.

Tracks runtimes the plugin has spawned so we don't blow past Pro+'s ~3
concurrent-session cap by leaving 12-24 h zombie runtimes holding every slot
(see browser.py for the war story this prevents).

The ledger is intentionally pessimistic: it only knows about runtimes WE
created. Real Google quota can drift below ours (Google reaped a runtime we
still think is alive) or above (user spawned runtimes in regular Colab UI).
Stale-entry sweep at 24 h matches Pro+ background execution max and is the
safety net for the first case.

File format: JSON array of {notebook_id, started_at, runtime_type, pid}.
Atomic across processes via filelock.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from filelock import FileLock

from . import paths as _paths

# Pro+ background execution caps sessions at 24 h. Anything older than that
# can't still be alive on Google's side, so we can safely drop it.
MAX_AGE = timedelta(hours=24)

# Ledger I/O is microseconds. A multi-second wait means a peer process is
# wedged — fail loud rather than block the user.
LOCK_TIMEOUT = 5.0


def _lock_path() -> str:
    return str(_paths.LEDGER_PATH) + ".lock"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_stale(entry: dict[str, Any], now: datetime) -> bool:
    raw = entry.get("started_at")
    if not isinstance(raw, str):
        return True
    try:
        started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now - started) > MAX_AGE


def _is_well_formed(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("notebook_id"), str)
        and isinstance(entry.get("started_at"), str)
    )


def _read_raw() -> list[dict[str, Any]]:
    path = _paths.LEDGER_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if _is_well_formed(e)]


def _write_raw(entries: list[dict[str, Any]]) -> None:
    path = _paths.LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read() -> list[dict[str, Any]]:
    """Return non-stale entries. Does not persist a sweep."""
    now = _now()
    return [e for e in _read_raw() if not _is_stale(e, now)]


def sweep() -> list[dict[str, Any]]:
    """Drop stale entries, persist, return live entries."""
    now = _now()
    with FileLock(_lock_path(), timeout=LOCK_TIMEOUT):
        entries = _read_raw()
        live = [e for e in entries if not _is_stale(e, now)]
        if len(live) != len(entries):
            _write_raw(live)
        return live


def add(
    notebook_id: str,
    runtime_type: str = "cpu",
    pid: int | None = None,
) -> dict[str, Any]:
    """Append an entry. Replaces any existing one for the same notebook_id."""
    now = _now()
    entry = {
        "notebook_id": notebook_id,
        "started_at": _iso(now),
        "runtime_type": runtime_type,
        "pid": pid if pid is not None else os.getpid(),
    }
    with FileLock(_lock_path(), timeout=LOCK_TIMEOUT):
        existing = _read_raw()
        kept = [
            e for e in existing if not _is_stale(e, now) and e.get("notebook_id") != notebook_id
        ]
        kept.append(entry)
        _write_raw(kept)
    return entry


def remove(notebook_id: str) -> bool:
    """Remove the entry for notebook_id. Returns True if removed, False if absent."""
    now = _now()
    with FileLock(_lock_path(), timeout=LOCK_TIMEOUT):
        entries = _read_raw()
        live_before = [e for e in entries if not _is_stale(e, now)]
        live_after = [e for e in live_before if e.get("notebook_id") != notebook_id]
        removed = len(live_after) != len(live_before)
        # Persist only if state actually changed (covers both removal and stale-sweep).
        if len(live_after) != len(entries):
            _write_raw(live_after)
        return removed


def preflight(cap: int) -> dict[str, Any]:
    """Check whether a new runtime can be created. Sweeps stale entries first."""
    active = sweep()
    if len(active) >= cap:
        ids = [e["notebook_id"] for e in active]
        return {
            "status": "rate_limited",
            "active_count": len(active),
            "cap": cap,
            "active": active,
            "hint": (
                f"Plugin is tracking {len(active)} active runtime(s), cap is {cap}. "
                f"Run /colab-close on one of: {ids} to free a slot."
            ),
        }
    return {
        "status": "ok",
        "active_count": len(active),
        "cap": cap,
        "active": active,
    }
