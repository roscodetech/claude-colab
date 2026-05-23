"""Client side of the persistent-session protocol.

The daemon is a long-running process that holds a Playwright session against
a single Colab notebook. Clients (the CLI, subagents) read its connection
details from session.json and exchange JSON-line messages over a localhost
TCP socket.

Stale-session detection: if session.json is on disk but the PID isn't alive
(daemon crashed), we treat it as no session and clean up the stale file.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

from . import paths as _paths

CONNECT_TIMEOUT_SEC = 5
# Per-recv timeout. run_all_native blocks the connection for the entire Run
# All (no streaming yet — see session_daemon.STREAM_COMMANDS for why); this
# has to absorb the longest notebook the user expects to run end-to-end.
# 4h covers a typical fine-tune. Bump if you need longer.
COMMAND_TIMEOUT_SEC = 14400


@dataclass
class SessionInfo:
    pid: int
    port: int
    file_id: str
    runtime: str
    started_at: float

    @classmethod
    def load(cls) -> SessionInfo | None:
        if not _paths.SESSION_PATH.exists():
            return None
        try:
            with _paths.SESSION_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            # Corrupt session file — treat as no session, leave it for cleanup.
            return None

    def write(self) -> None:
        _paths.HOME.mkdir(parents=True, exist_ok=True)
        with _paths.SESSION_PATH.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)


def pid_alive(pid: int) -> bool:
    """Cross-platform PID liveness probe. False on stale/exited PIDs."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION (0x1000) — minimal
        # rights required to detect existence without raising on protected procs.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        # Even open handles can refer to a zombie that has exited. Check exit code.
        STILL_ACTIVE = 259
        exit_code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return bool(ok) and exit_code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def get_active_session() -> SessionInfo | None:
    """Return live session info, or None. Cleans up stale session.json."""
    info = SessionInfo.load()
    if info is None:
        return None
    if not pid_alive(info.pid):
        # Stale — clean up.
        with contextlib.suppress(OSError):
            _paths.SESSION_PATH.unlink()
        return None
    return info


def session_for(file_id: str) -> SessionInfo | None:
    """Active session for the given file_id, or None. Other-file sessions
    return None (caller should error-out so they don't blindly run against
    the wrong notebook)."""
    info = get_active_session()
    if info and info.file_id == file_id:
        return info
    return None


# ---------- IPC ----------


def send(cmd: str, info: SessionInfo | None = None, **args: Any) -> dict[str, Any]:
    """Send one command, read the terminal JSON-line response. Raises on
    connect failure.

    For streaming commands (run_all_native) intermediate `{"progress": true}`
    lines are silently dropped; this returns the final `{"done": true}` line.
    Use `send_stream` to observe progress events.
    """
    if info is None:
        info = get_active_session()
    if info is None:
        raise SessionUnavailable("no active session")

    final: dict[str, Any] | None = None
    for line in _send_stream(cmd, info=info, **args):
        # Skip per-progress heartbeats; only keep terminal responses.
        if line.get("progress") and not line.get("done"):
            continue
        final = line
        if line.get("done") or line.get("status") in ("ok", "error"):
            break
    if final is None:
        raise SessionUnavailable("daemon closed connection without responding")
    return final


def send_stream(cmd: str, info: SessionInfo | None = None, **args: Any):
    """Send one command, yield each JSON-line response as it arrives.

    Use for streaming commands (run_all_native): the daemon emits a `progress`
    line on every state change, then a final `done: true` line. The yielded
    iterator finishes when the daemon closes the connection.
    """
    if info is None:
        info = get_active_session()
    if info is None:
        raise SessionUnavailable("no active session")
    yield from _send_stream(cmd, info=info, **args)


def _send_stream(cmd: str, info: SessionInfo, **args: Any):
    sock = socket.create_connection(("127.0.0.1", info.port), timeout=CONNECT_TIMEOUT_SEC)
    sock.settimeout(COMMAND_TIMEOUT_SEC)
    try:
        payload = json.dumps({"cmd": cmd, **args}) + "\n"
        sock.sendall(payload.encode("utf-8"))
        buf = bytearray()
        sent_anything = False
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf.extend(chunk)
            # Emit complete lines as we get them.
            while b"\n" in buf:
                line, _, rest = buf.partition(b"\n")
                buf = bytearray(rest)
                if not line:
                    continue
                try:
                    yield json.loads(line.decode("utf-8"))
                    sent_anything = True
                except json.JSONDecodeError:
                    continue
        if not sent_anything:
            raise SessionUnavailable("daemon closed connection without responding")
    finally:
        with contextlib.suppress(OSError):
            sock.close()


def ping(info: SessionInfo | None = None) -> bool:
    """True if daemon answers a ping. Used to verify a freshly-spawned daemon
    has finished initializing before we hand control back to the user."""
    try:
        res = send("ping", info=info)
        return res.get("status") == "ok"
    except (OSError, SessionUnavailable, json.JSONDecodeError):
        return False


def wait_until_ready(timeout_sec: float = 90.0, poll_sec: float = 0.5) -> SessionInfo | None:
    """Block until the daemon's session.json appears AND it answers a ping.

    Used by /colab-open after spawning the daemon — first cell run should
    succeed immediately rather than racing with browser startup.
    """
    deadline = time.time() + timeout_sec
    last_info: SessionInfo | None = None
    while time.time() < deadline:
        info = get_active_session()
        if info is not None:
            last_info = info
            if ping(info):
                return info
        time.sleep(poll_sec)
    return last_info  # may be None or a non-responding session


class SessionUnavailable(RuntimeError):
    """No active session, or daemon refused/dropped the connection."""
