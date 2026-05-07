"""Persistent Colab session daemon.

A long-running process that opens a Playwright/Chrome session against one
notebook, holds the file lock for its lifetime, and serves cell-run commands
over a localhost TCP socket so successive /colab-run calls share kernel state.

Spawned by /colab-open. Closed by /colab-close (or process death).

Logs to ~/.claude-colab/session.log. The daemon's stdout/stderr are detached
from the parent — the log file is the only debugging surface.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

# Allow `python -m scripts.session_daemon ...` and direct invocation.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import browser
    from scripts import paths as _paths
    from scripts.session_client import SessionInfo
else:
    from . import browser
    from . import paths as _paths
    from .session_client import SessionInfo


def _log(msg: str) -> None:
    """Append a timestamped line to session.log. Best-effort — never raise."""
    try:
        with _paths.SESSION_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _kill_orphan_chromiums(profile_dir: str) -> None:
    """Force-kill any Chromium with our profile dir in its command line.

    Backstop for Playwright leaving orphaned Chrome processes when ColabSession
    crashes during __enter__ — observed empirically. Targets only our specific
    profile, so the user's regular Chrome is untouched.
    """
    import subprocess

    try:
        if sys.platform == "win32":
            # PowerShell is more reliable than wmic (deprecated on Win11).
            ps_script = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" |"
                f" Where-Object {{ $_.CommandLine -like '*{profile_dir}*' }} |"
                " ForEach-Object { Stop-Process -Id $_.ProcessId -Force"
                " -ErrorAction SilentlyContinue }"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                timeout=10,
            )
        else:
            subprocess.run(["pkill", "-f", profile_dir], capture_output=True, timeout=5)
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass


HEARTBEAT_INTERVAL_SEC = 15.0


class Daemon:
    def __init__(self, file_id: str, runtime: str, port: int):
        self.file_id = file_id
        self.runtime = runtime
        self.port = port
        self.started_at = time.time()
        self.session: browser.ColabSession | None = None
        self._stop = threading.Event()
        # Mutex around session access. Multiple connections can hit run_cell
        # concurrently; the underlying Playwright page is single-threaded use.
        self._session_lock = threading.Lock()
        # Progress state — read by ping, written by run handlers. Plain attrs
        # are atomic enough for these reads/writes (no torn-read risk for
        # immutable types, and we accept a stale read in exchange for not
        # serializing ping behind run_cell).
        self._running_cell: str | None = None
        self._running_started_at: float | None = None

    # ---------- Command dispatch ----------

    def _dismiss_blocking_dialogs(self) -> int:
        """Force-close any open mwc-dialog. Colab pops these for runtime errors
        and for "notebook modified externally" warnings, and they intercept
        pointer events on every cell. Returns the count dismissed."""
        if self.session is None or self.session.page is None:
            return 0
        try:
            n = self.session.page.evaluate(
                "() => { const ds = document.querySelectorAll('mwc-dialog[open]');"
                " for (const d of ds) { d.removeAttribute('open'); d.style.display='none'; }"
                " return ds.length; }"
            )
            if n:
                _log(f"dismissed {n} mwc-dialog(s)")
            return int(n)
        except Exception as e:
            _log(f"dismiss_dialogs failed: {e}")
            return 0

    def _running_state(self) -> dict | None:
        """Snapshot of the in-progress cell, if any. Used by ping responses."""
        cid = self._running_cell
        started = self._running_started_at
        if cid is None or started is None:
            return None
        return {"cell_id": cid, "elapsed_sec": int(time.time() - started)}

    def handle(self, payload: dict) -> dict:
        cmd = payload.get("cmd")
        try:
            if cmd == "ping":
                # Lock-free path — readers tolerate a stale snapshot in exchange
                # for not blocking behind a 5-minute run_cell.
                return {
                    "status": "ok",
                    "uptime_sec": int(time.time() - self.started_at),
                    "file_id": self.file_id,
                    "runtime": self.runtime,
                    "running": self._running_state(),
                }
            if cmd == "dismiss_dialogs":
                return {"status": "ok", "dismissed": self._dismiss_blocking_dialogs()}
            if cmd == "run_cell":
                cell_id = payload.get("cell_id")
                if not cell_id:
                    return {"status": "error", "error": "cell_id required"}
                timeout = int(payload.get("timeout_sec", browser.DEFAULT_RUN_TIMEOUT))
                with self._session_lock:
                    self._dismiss_blocking_dialogs()
                    self._running_cell = cell_id
                    self._running_started_at = time.time()
                    try:
                        result = self.session.run_cell(cell_id, timeout_sec=timeout)
                    finally:
                        self._running_cell = None
                        self._running_started_at = None
                return {"status": "ok", "result": result.to_dict()}
            if cmd == "run_all":
                with self._session_lock:
                    self._running_cell = "<all>"
                    self._running_started_at = time.time()
                    try:
                        results = self.session.run_all()
                    finally:
                        self._running_cell = None
                        self._running_started_at = None
                return {"status": "ok", "results": [r.to_dict() for r in results]}
            if cmd == "run_all_native":
                # Trigger Colab's own "Run all" via keyboard shortcut (Ctrl+F9).
                # Colab then handles cell ordering, kernel-restart prompts, and
                # cached-output invalidation natively. Poll for completion by
                # watching the count of running/queued cells.
                page = self.session.page
                self._dismiss_blocking_dialogs()
                # Focus the notebook so the shortcut hits Colab's own listener
                # rather than the OS / browser.
                page.click("body")
                page.keyboard.press("Control+F9")
                deadline = time.time() + int(payload.get("timeout_sec", 3600))
                last_state = None
                first_seen_running = False
                while time.time() < deadline:
                    time.sleep(2.0)
                    self._dismiss_blocking_dialogs()
                    state = page.evaluate(
                        "() => ({"
                        "  running: document.querySelectorAll('.cell.code.running').length,"
                        "  queued: document.querySelectorAll('.cell.code.pending,.cell.code.queued').length,"
                        "  total: document.querySelectorAll('.cell.code').length,"
                        "})"
                    )
                    if state != last_state:
                        _log(f"run_all_native: {state}")
                        last_state = state
                    if state["running"] > 0:
                        first_seen_running = True
                    elif first_seen_running and state["queued"] == 0:
                        break
                else:
                    return {"status": "error", "error": "run_all_native timed out"}
                return {"status": "ok", "final_state": state}
            if cmd == "quit":
                self._stop.set()
                return {"status": "ok", "shutting_down": True}
            return {"status": "error", "error": f"unknown command: {cmd!r}"}
        except Exception as e:
            _log(f"handler error on {cmd}: {e}\n{traceback.format_exc()}")
            return {"status": "error", "error": str(e), "trace": traceback.format_exc()}

    # ---------- Server loop ----------

    def bind(self) -> socket.socket:
        """Bind the listening socket. If port was 0, OS assigns one and we
        store the real port so session.json reflects the actual value."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.port))
        self.port = srv.getsockname()[1]
        srv.listen(4)
        srv.settimeout(0.5)  # short timeout so we can poll _stop
        _log(f"daemon listening on 127.0.0.1:{self.port}")
        return srv

    def serve_loop(self, srv: socket.socket) -> None:
        """Accept connections and dispatch each on its own daemon thread.

        Multi-threaded so `ping` can answer while a long `run_cell` is in
        flight — without it, /colab-status would hang for the full duration.
        Session access is serialized via self._session_lock; ping is
        lock-free and reads the running-state snapshot directly.
        """
        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError as e:
                _log(f"accept error: {e}")
                break
            t = threading.Thread(target=self._serve_one, args=(conn,), daemon=True)
            t.start()
        srv.close()
        _log("daemon stopped serving")

    def _serve_one(self, conn) -> None:
        with conn:
            try:
                conn.settimeout(60)
                data = bytearray()
                while not data.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                if not data:
                    return
                payload = json.loads(data.decode("utf-8").rstrip("\n"))
                response = self.handle(payload)
                conn.sendall((json.dumps(response, default=str) + "\n").encode("utf-8"))
            except Exception as e:
                _log(f"connection error: {e}\n{traceback.format_exc()}")
                with contextlib.suppress(OSError):
                    conn.sendall(
                        (json.dumps({"status": "error", "error": str(e)}) + "\n").encode("utf-8")
                    )

    def heartbeat_loop(self) -> None:
        """Background thread: while a cell is running, write a progress line
        to session.log every HEARTBEAT_INTERVAL_SEC. Lets users tailing the
        log see that work is happening without polling /colab-status.
        """
        last_logged_for: tuple[str, int] | None = None
        while not self._stop.is_set():
            self._stop.wait(HEARTBEAT_INTERVAL_SEC)
            state = self._running_state()
            if state is None:
                last_logged_for = None
                continue
            # Only log when the elapsed bucket has changed — avoids flooding
            # the log with identical lines if a cell stalls before our poll.
            bucket = (state["cell_id"], state["elapsed_sec"] // 5)
            if bucket == last_logged_for:
                continue
            last_logged_for = bucket
            _log(f"[heartbeat] cell {state['cell_id']} running for {state['elapsed_sec']}s")

    # ---------- Lifecycle ----------

    def run(self) -> int:
        # Mutex via session.json + PID liveness — NOT FileLock. On Windows,
        # Chromium subprocesses inherit our lock-file handle and don't release
        # it until they're killed too, so a crashed daemon leaves a stuck
        # FileLock for minutes. session.json + pid_alive() is robust to that.
        from . import session_client

        existing = session_client.get_active_session()
        if existing is not None:
            _log(
                f"another daemon is already active (pid={existing.pid}, file_id={existing.file_id})"
            )
            return 2

        srv = None
        try:
            # Bind the socket first so we know the real port (if port=0).
            srv = self.bind()

            # Open the browser session.
            _log(f"opening notebook {self.file_id} (runtime={self.runtime!r})")
            self.session = browser.ColabSession(self.file_id, runtime=self.runtime)
            self.session.__enter__()
            self.session.connect_runtime(self.runtime)
            _log("browser session up")

            # Publish session.json so clients can find us. Done AFTER session
            # is up AND socket is bound so wait_until_ready() ping works first try.
            SessionInfo(
                pid=os.getpid(),
                port=self.port,
                file_id=self.file_id,
                runtime=self.runtime,
                started_at=self.started_at,
            ).write()

            # Heartbeat thread — daemon=True so it dies with the process.
            hb = threading.Thread(target=self.heartbeat_loop, daemon=True)
            hb.start()

            self.serve_loop(srv)
            return 0
        except Exception as e:
            _log(f"daemon crashed: {e}\n{traceback.format_exc()}")
            return 1
        finally:
            # Cleanup ordering:
            # 1. Try the clean Playwright shutdown (closes browser context).
            # 2. Backstop: force-kill any Chromium with our profile dir in its
            #    cmdline. Playwright leaves orphans when __enter__ crashes
            #    mid-init (e.g. network error during goto), and those orphans
            #    keep the profile dir locked for the next /colab-open.
            # 3. Delete session.json so clients stop trying to reach us.
            with contextlib.suppress(Exception):
                if self.session is not None:
                    self.session.__exit__(None, None, None)
            with contextlib.suppress(Exception):
                _kill_orphan_chromiums(str(_paths.BROWSER_PROFILE_DIR))
            with contextlib.suppress(OSError):
                if _paths.SESSION_PATH.exists():
                    _paths.SESSION_PATH.unlink()
            _log("daemon shut down")


def _install_signal_handlers(daemon: Daemon) -> None:
    """Translate SIGTERM/SIGINT into a clean stop. SIGBREAK on Windows."""

    def _handler(signum, _frame):
        _log(f"received signal {signum}; stopping")
        daemon._stop.set()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, _handler)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="claude-colab-session-daemon")
    p.add_argument("--file-id", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--runtime", default="cpu")
    args = p.parse_args(argv)

    _paths.HOME.mkdir(parents=True, exist_ok=True)
    _log(f"starting pid={os.getpid()} file={args.file_id} port={args.port}")

    daemon = Daemon(file_id=args.file_id, runtime=args.runtime, port=args.port)
    _install_signal_handlers(daemon)
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
