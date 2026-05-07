"""Single CLI entrypoint. Commands and subagents shell out to this.

Output is JSON by default (machine-friendly for agent consumption); pass
--human for terminal-readable output.

Usage:
    python -m scripts.cli <subcommand> [args]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# Allow direct invocation (`python scripts/cli.py`) and module invocation.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import auth, browser, config, drive, notebook, paths, session_client
else:
    from . import auth, browser, config, drive, notebook, paths, session_client


# ---------- helpers ----------


def _emit(data: Any, human: bool = False) -> int:
    if human:
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2))
        else:
            print(data)
    else:
        print(json.dumps(data, default=str))
    return 0


def _fail(msg: str, code: int = 1, human: bool = False, **extra: Any) -> int:
    payload = {"status": "error", "error": msg, **extra}
    if human:
        print(f"error: {msg}", file=sys.stderr)
    else:
        print(json.dumps(payload), file=sys.stderr)
    return code


# ---------- subcommands ----------


def cmd_init(args: argparse.Namespace) -> int:
    """First-run wizard. Idempotent; --reset wipes back to defaults."""
    if args.reset:
        cfg = config.reset()
        return _emit({"status": "ok", "config": cfg, "reset": True}, args.human)

    cfg = config.load()
    # Apply any flag overrides.
    patches: dict[str, Any] = {}
    if args.scope_folder is not None:
        patches["drive_scope_folder"] = args.scope_folder
        patches["drive_scope_full"] = False
    if args.scope_full:
        patches["drive_scope_full"] = True
    if args.no_images:
        patches["save_images"] = False
    if args.images:
        patches["save_images"] = True
    if args.retries is not None:
        patches["debugger_max_retries"] = args.retries
    if args.runtime is not None:
        patches["default_runtime"] = args.runtime

    if patches:
        cfg = config.update(**patches)
    return _emit({"status": "ok", "config": cfg, "home": str(paths.HOME)}, args.human)


def cmd_auth(args: argparse.Namespace) -> int:
    creds = auth.authorize_drive(force=args.force)
    return _emit({"status": "ok", "scopes": list(creds.scopes or [])}, args.human)


def cmd_login(args: argparse.Namespace) -> int:
    res = auth.login_browser(timeout_sec=args.timeout)
    return _emit(res, args.human)


def cmd_list(args: argparse.Namespace) -> int:
    files = drive.list_notebooks(page_size=args.limit)
    return _emit({"status": "ok", "notebooks": files}, args.human)


def cmd_new(args: argparse.Namespace) -> int:
    meta = drive.create_notebook(args.name)
    return _emit({"status": "ok", "notebook": meta}, args.human)


def cmd_delete(args: argparse.Namespace) -> int:
    drive.delete_notebook(args.file_id, hard=args.hard)
    return _emit({"status": "ok", "file_id": args.file_id, "hard": args.hard}, args.human)


def cmd_show(args: argparse.Namespace) -> int:
    """Summarize cells in a notebook — for agents inspecting before editing."""
    nb, rev = notebook.read(args.file_id)
    return _emit(
        {
            "status": "ok",
            "file_id": args.file_id,
            "revision": rev,
            "cells": notebook.summarize(nb),
        },
        args.human,
    )


def cmd_edit(args: argparse.Namespace) -> int:
    # Resolve source up front so we can validate args before any IO.
    if args.source is not None:
        source = args.source
    elif args.source_file is not None:
        source = Path(args.source_file).read_text(encoding="utf-8")
    else:
        source = None

    # Validate args before fetching from Drive — fail-fast saves a network call.
    if args.action == "add" and source is None:
        return _fail("--source or --source-file required for add", human=args.human)
    if args.action == "edit" and (source is None or args.cell is None):
        return _fail("--cell and --source/--source-file required for edit", human=args.human)
    if args.action == "delete" and args.cell is None:
        return _fail("--cell required for delete", human=args.human)

    nb, rev = notebook.read(args.file_id)

    if args.action == "add":
        cid = notebook.add_cell(nb, source, cell_type=args.type, after=args.after)
    elif args.action == "edit":
        cid = notebook.edit_cell(nb, args.cell, source)
    elif args.action == "delete":
        cid = notebook.delete_cell(nb, args.cell)
    else:
        return _fail(f"unknown action: {args.action}", human=args.human)

    meta = notebook.write(args.file_id, nb, expected_revision=rev)
    return _emit(
        {"status": "ok", "cell_id": cid, "revision": meta.get("headRevisionId")}, args.human
    )


def cmd_open(args: argparse.Namespace) -> int:
    """Spawn the persistent session daemon for a notebook.

    Holds a long-lived browser + warm runtime so successive /colab-run calls
    share kernel state. Only one session at a time (lock-enforced).
    """
    existing = session_client.get_active_session()
    if existing is not None:
        if existing.file_id == args.file_id:
            return _emit(
                {
                    "status": "ok",
                    "session": {
                        "pid": existing.pid,
                        "port": existing.port,
                        "file_id": existing.file_id,
                        "runtime": existing.runtime,
                        "uptime_sec": int(time.time() - existing.started_at),
                    },
                    "note": "session already active for this notebook",
                },
                args.human,
            )
        return _fail(
            f"another session is already active for {existing.file_id!r} "
            "(/colab-close first, or use /colab-status to inspect)",
            human=args.human,
        )

    runtime = args.runtime or config.load().get("default_runtime", "cpu")
    pid = _spawn_session_daemon(args.file_id, runtime)
    info = session_client.wait_until_ready(timeout_sec=args.timeout)
    if info is None:
        # Daemon never came up. Try to kill it so we don't leak a zombie.
        _kill_pid(pid)
        return _fail(
            "session daemon failed to start within timeout; "
            f"see {paths.SESSION_LOG_PATH} for details",
            human=args.human,
        )

    return _emit(
        {
            "status": "ok",
            "session": {
                "pid": info.pid,
                "port": info.port,
                "file_id": info.file_id,
                "runtime": info.runtime,
            },
        },
        args.human,
    )


def cmd_close(args: argparse.Namespace) -> int:
    """Tell the active session daemon to exit cleanly."""
    info = session_client.get_active_session()
    if info is None:
        return _emit({"status": "ok", "note": "no active session"}, args.human)

    try:
        res = session_client.send("quit", info=info)
    except (session_client.SessionUnavailable, OSError) as e:
        # Daemon is unreachable but session.json says alive — force-kill PID.
        _kill_pid(info.pid)
        with __import__("contextlib").suppress(OSError):
            paths.SESSION_PATH.unlink()
        return _emit(
            {"status": "ok", "note": f"daemon unreachable, force-killed pid {info.pid}: {e}"},
            args.human,
        )
    return _emit({"status": "ok", "response": res}, args.human)


def cmd_status(args: argparse.Namespace) -> int:
    """Report on the active session, if any."""
    info = session_client.get_active_session()
    if info is None:
        return _emit({"status": "ok", "active": False}, args.human)

    # Verify the daemon is responsive, not just alive.
    responsive = session_client.ping(info)
    return _emit(
        {
            "status": "ok",
            "active": True,
            "responsive": responsive,
            "session": {
                "pid": info.pid,
                "port": info.port,
                "file_id": info.file_id,
                "runtime": info.runtime,
                "uptime_sec": int(time.time() - info.started_at),
            },
        },
        args.human,
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Run a cell or all cells. Uses the active session if it matches the
    requested file_id; otherwise falls back to ephemeral run (browser
    spin-up + tear-down per call — no shared kernel state).
    """
    want_all = args.cell == "all" or (args.cell is None and args.all)
    if not want_all and args.cell is None:
        return _fail("provide --cell <id> or --all", human=args.human)

    sess = session_client.get_active_session()

    # If a session is up for a DIFFERENT notebook, fail loud — running
    # ephemerally would block on the lock anyway and produce a confusing error.
    if sess is not None and sess.file_id != args.file_id:
        return _fail(
            f"another notebook ({sess.file_id!r}) has an active session; "
            "/colab-close first or run against that notebook",
            human=args.human,
        )

    if sess is not None:
        # Use the persistent session — fast, kernel state preserved.
        try:
            if want_all:
                res = session_client.send("run_all", info=sess)
                return _emit(
                    {"status": "ok", "via": "session", "results": res.get("results", [])},
                    args.human,
                )
            res = session_client.send(
                "run_cell", info=sess, cell_id=args.cell, timeout_sec=args.timeout
            )
            return _emit(
                {"status": "ok", "via": "session", "result": res.get("result")}, args.human
            )
        except session_client.SessionUnavailable as e:
            return _fail(f"session unreachable: {e}", human=args.human)

    # Ephemeral fallback. Warn — for iterative work the user almost always
    # wants /colab-open instead.
    if want_all:
        results = browser.run_all_cells(args.file_id, runtime=args.runtime)
        return _emit({"status": "ok", "via": "ephemeral", "results": results}, args.human)
    res = browser.run_one_cell(
        args.file_id, args.cell, runtime=args.runtime, timeout_sec=args.timeout
    )
    return _emit({"status": "ok", "via": "ephemeral", "result": res}, args.human)


def _spawn_session_daemon(file_id: str, runtime: str) -> int:
    """Detached spawn of session_daemon. Returns the child PID.

    On Windows uses DETACHED_PROCESS so the daemon outlives this CLI invocation.
    On POSIX uses start_new_session=True (setsid).
    """
    import subprocess

    cmd = [
        sys.executable,
        "-m",
        "scripts.session_daemon",
        "--file-id",
        file_id,
        "--runtime",
        runtime,
        "--port",
        "0",
    ]
    kwargs: dict[str, Any] = {
        "cwd": str(paths.PLUGIN_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return proc.pid


def _kill_pid(pid: int) -> None:
    """Best-effort kill of a daemon PID. Used on startup-failure cleanup."""
    if pid <= 0:
        return
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            if handle:
                kernel32.TerminateProcess(handle, 1)
                kernel32.CloseHandle(handle)
        else:
            import signal as _signal

            os.kill(pid, _signal.SIGTERM)
    except Exception:
        pass


def cmd_output(args: argparse.Namespace) -> int:
    nb, _ = notebook.read(args.file_id)
    text = notebook.cell_outputs_text(nb, args.cell)
    return _emit({"status": "ok", "cell": args.cell, "text": text}, args.human)


def cmd_scope(args: argparse.Namespace) -> int:
    cfg = config.load()
    note: str | None = None

    if args.oauth is not None:
        if args.oauth not in ("file", "full"):
            return _fail(f"--oauth must be 'file' or 'full', got {args.oauth!r}", human=args.human)
        if args.oauth != cfg.get("oauth_scope", "file"):
            cfg = auth.set_oauth_scope(args.oauth)
            # Re-auth doesn't auto-trigger here — happens lazily on next Drive
            # call. Surface the prompt explicitly so users know to expect it.
            note = "OAuth scope changed; re-run /colab-auth to grant new consent"

    if args.full:
        cfg = config.update(drive_scope_full=True)
    elif args.folder is not None:
        cfg = config.update(drive_scope_folder=args.folder, drive_scope_full=False)

    payload: dict[str, Any] = {
        "status": "ok",
        "scope": {
            "oauth": cfg.get("oauth_scope", "file"),
            "folder": cfg.get("drive_scope_folder"),
            "full": cfg.get("drive_scope_full"),
        },
    }
    if note:
        payload["note"] = note
    return _emit(payload, args.human)


def cmd_selftest(args: argparse.Namespace) -> int:
    """Smoke-test: create canary, run print/plot/error cells, report broken selectors."""
    from . import selftest

    return _emit(selftest.run(), args.human)


# ---------- argparse ----------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-colab",
        description="Drive Google Colab from Claude Code. Pass --human after a subcommand for indented output.",
    )
    # Parent parser: cross-cutting flags every subcommand inherits via parents=.
    # Kept off the top-level parser so the subparser's default doesn't clobber it.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--human", action="store_true", help="human-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", parents=[shared])
    sp.add_argument("--scope-folder")
    sp.add_argument("--scope-full", action="store_true")
    sp.add_argument("--images", action="store_true")
    sp.add_argument("--no-images", action="store_true")
    sp.add_argument("--retries", type=int)
    sp.add_argument("--runtime", choices=["cpu", "gpu", "tpu"])
    sp.add_argument("--reset", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("auth", parents=[shared])
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_auth)

    sp = sub.add_parser("login", parents=[shared])
    sp.add_argument("--timeout", type=int, default=300)
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("list", parents=[shared])
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("new", parents=[shared])
    sp.add_argument("name")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("delete", parents=[shared])
    sp.add_argument("file_id")
    sp.add_argument("--hard", action="store_true")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("show", parents=[shared])
    sp.add_argument("file_id")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("edit", parents=[shared])
    sp.add_argument("file_id")
    sp.add_argument("action", choices=["add", "edit", "delete"])
    sp.add_argument("--cell", help="cell id or index for edit/delete")
    sp.add_argument("--type", choices=["code", "markdown"], default="code")
    sp.add_argument("--after", help="cell id or index to insert after (add only)")
    sp.add_argument("--source", help="cell source text")
    sp.add_argument("--source-file", help="path to file containing source")
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser("open", parents=[shared])
    sp.add_argument("file_id")
    sp.add_argument("--runtime", choices=["cpu", "gpu", "tpu"])
    sp.add_argument("--timeout", type=int, default=120, help="seconds to wait for daemon ready")
    sp.set_defaults(func=cmd_open)

    sp = sub.add_parser("close", parents=[shared])
    sp.set_defaults(func=cmd_close)

    sp = sub.add_parser("status", parents=[shared])
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("run", parents=[shared])
    sp.add_argument("file_id")
    sp.add_argument("--cell", help="cell id, or 'all'")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--runtime", choices=["cpu", "gpu", "tpu"])
    sp.add_argument("--timeout", type=int, default=600)
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("output", parents=[shared])
    sp.add_argument("file_id")
    sp.add_argument("cell")
    sp.set_defaults(func=cmd_output)

    sp = sub.add_parser("scope", parents=[shared])
    sp.add_argument("--folder", help="restrict listing to a Drive folder name")
    sp.add_argument("--full", action="store_true", help="lift folder restriction")
    sp.add_argument(
        "--oauth",
        choices=["file", "full"],
        help="OAuth scope: 'file' (only files we created) or 'full' (read+write all)",
    )
    sp.set_defaults(func=cmd_scope)

    sp = sub.add_parser("selftest", parents=[shared])
    sp.set_defaults(func=cmd_selftest)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as e:
        if getattr(args, "human", False):
            traceback.print_exc()
            return 1
        return _fail(str(e), trace=traceback.format_exc())


if __name__ == "__main__":
    sys.exit(main())
