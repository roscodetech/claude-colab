"""SessionInfo, stale-session detection, IPC dispatch.

Daemon spawning is not tested here (would require real Chromium); we test
the client-side logic against a simulated session.json file.
"""

from __future__ import annotations

import json
import os
import socket
import threading

import pytest

from scripts import paths, session_client


def _write_session_file(pid: int = None, port: int = 12345, file_id: str = "abc") -> None:
    """Write a synthetic session.json. Defaults to current pid (alive)."""
    paths.SESSION_PATH.write_text(
        json.dumps(
            {
                "pid": pid if pid is not None else os.getpid(),
                "port": port,
                "file_id": file_id,
                "runtime": "cpu",
                "started_at": 0.0,
            }
        ),
        encoding="utf-8",
    )


def test_get_active_session_returns_none_when_no_file():
    assert session_client.get_active_session() is None


def test_get_active_session_returns_info_when_pid_alive():
    _write_session_file()
    info = session_client.get_active_session()
    assert info is not None
    assert info.file_id == "abc"
    assert info.port == 12345


def test_get_active_session_cleans_up_stale_file():
    """A session.json with a dead PID should be deleted, returning None."""
    _write_session_file(pid=999_999_999)
    assert paths.SESSION_PATH.exists()

    info = session_client.get_active_session()
    assert info is None
    assert not paths.SESSION_PATH.exists()  # cleaned up


def test_get_active_session_handles_corrupt_file():
    paths.SESSION_PATH.write_text("not json", encoding="utf-8")
    assert session_client.get_active_session() is None


def test_session_for_matching_file_id():
    _write_session_file(file_id="my-nb")
    assert session_client.session_for("my-nb") is not None
    assert session_client.session_for("other") is None


def test_pid_alive_self():
    assert session_client.pid_alive(os.getpid())


def test_pid_alive_zero_or_negative():
    assert not session_client.pid_alive(0)
    assert not session_client.pid_alive(-1)


def test_pid_alive_dead_pid():
    assert not session_client.pid_alive(999_999_999)


def test_send_raises_when_no_session():
    with pytest.raises(session_client.SessionUnavailable):
        session_client.send("ping")


def test_ping_returns_false_for_unreachable_port():
    _write_session_file(port=1)
    info = session_client.get_active_session()
    assert info is not None
    assert session_client.ping(info) is False


def _fake_daemon(port_holder: list[int], handler) -> None:
    """Tiny socket server that mimics the daemon protocol for IPC tests."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port_holder.append(srv.getsockname()[1])
    srv.settimeout(5)
    try:
        conn, _ = srv.accept()
        with conn:
            data = bytearray()
            while not data.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data.extend(chunk)
            req = json.loads(data.decode("utf-8").rstrip("\n"))
            response = handler(req)
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
    finally:
        srv.close()


def test_send_round_trips_against_fake_daemon():
    port_holder: list[int] = []

    def handler(req):
        assert req["cmd"] == "ping"
        return {"status": "ok", "uptime_sec": 7}

    t = threading.Thread(target=_fake_daemon, args=(port_holder, handler))
    t.start()
    while not port_holder:
        pass
    _write_session_file(port=port_holder[0])

    res = session_client.send("ping")
    assert res == {"status": "ok", "uptime_sec": 7}
    t.join(timeout=5)


def test_send_passes_kwargs_as_payload():
    port_holder: list[int] = []
    received: dict = {}

    def handler(req):
        received.update(req)
        return {"status": "ok"}

    t = threading.Thread(target=_fake_daemon, args=(port_holder, handler))
    t.start()
    while not port_holder:
        pass
    _write_session_file(port=port_holder[0])

    session_client.send("run_cell", cell_id="abc", timeout_sec=42)
    assert received == {"cmd": "run_cell", "cell_id": "abc", "timeout_sec": 42}
    t.join(timeout=5)
