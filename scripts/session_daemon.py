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


class Daemon:
    def __init__(self, file_id: str, runtime: str, port: int):
        self.file_id = file_id
        self.runtime = runtime
        self.port = port
        self.started_at = time.time()
        self.session: browser.ColabSession | None = None
        self._stop = threading.Event()

    # ---------- Command dispatch ----------

    def handle(self, payload: dict) -> dict:
        cmd = payload.get("cmd")
        try:
            if cmd == "ping":
                return {
                    "status": "ok",
                    "uptime_sec": int(time.time() - self.started_at),
                    "file_id": self.file_id,
                    "runtime": self.runtime,
                }
            if cmd == "run_cell":
                cell_id = payload.get("cell_id")
                if not cell_id:
                    return {"status": "error", "error": "cell_id required"}
                timeout = int(payload.get("timeout_sec", browser.DEFAULT_RUN_TIMEOUT))
                result = self.session.run_cell(cell_id, timeout_sec=timeout)
                return {"status": "ok", "result": result.to_dict()}
            if cmd == "run_all":
                results = self.session.run_all()
                return {"status": "ok", "results": [r.to_dict() for r in results]}
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
        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError as e:
                _log(f"accept error: {e}")
                break
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
                        continue
                    payload = json.loads(data.decode("utf-8").rstrip("\n"))
                    response = self.handle(payload)
                    conn.sendall((json.dumps(response, default=str) + "\n").encode("utf-8"))
                except Exception as e:
                    _log(f"connection error: {e}\n{traceback.format_exc()}")
                    with contextlib.suppress(OSError):
                        conn.sendall(
                            (json.dumps({"status": "error", "error": str(e)}) + "\n").encode(
                                "utf-8"
                            )
                        )
        srv.close()
        _log("daemon stopped serving")

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
