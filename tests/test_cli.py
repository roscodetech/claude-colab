"""CLI dispatch — argparse routing + JSON output shape.

We mock the underlying layers so we test cli.py's own logic, not transitively
re-test drive/notebook/browser.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from scripts import cli


def _run(*argv) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(list(argv))
    out = buf.getvalue().strip()
    data = json.loads(out) if out else {}
    return rc, data


def _run_raw(*argv) -> tuple[int, str]:
    """Like _run but returns raw stdout — for asserting on JSON formatting."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(list(argv))
    return rc, buf.getvalue()


def test_init_default_returns_config():
    rc, data = _run("init")
    assert rc == 0
    assert data["status"] == "ok"
    assert data["config"]["debugger_max_retries"] == 2


def test_init_patches_retries_flag():
    rc, data = _run("init", "--retries", "5")
    assert rc == 0
    assert data["config"]["debugger_max_retries"] == 5


def test_init_reset_restores_defaults():
    _run("init", "--retries", "9")
    rc, data = _run("init", "--reset")
    assert rc == 0
    assert data["config"]["debugger_max_retries"] == 2


def test_scope_full_flag_sets_config():
    rc, data = _run("scope", "--full")
    assert rc == 0
    assert data["scope"]["full"] is True


def test_scope_folder_clears_full():
    _run("scope", "--full")
    rc, data = _run("scope", "--folder", "x")
    assert data["scope"]["folder"] == "x"
    assert data["scope"]["full"] is False


def test_list_passes_through_drive(monkeypatch):
    fake_files = [{"id": "1", "name": "a.ipynb", "modifiedTime": "now", "webViewLink": "u"}]
    monkeypatch.setattr(cli.drive, "list_notebooks", lambda page_size: fake_files)
    rc, data = _run("list")
    assert rc == 0
    assert data["notebooks"] == fake_files


def test_new_calls_create(monkeypatch):
    monkeypatch.setattr(
        cli.drive, "create_notebook", lambda name: {"id": "nid", "name": f"{name}.ipynb"}
    )
    rc, data = _run("new", "thing")
    assert rc == 0
    assert data["notebook"]["id"] == "nid"


def test_show_summarizes(monkeypatch):
    from scripts import notebook as nbmod

    nb = nbmod.empty_notebook()
    monkeypatch.setattr(cli.notebook, "read", lambda fid: (nb, "rev1"))
    rc, data = _run("show", "abc")
    assert rc == 0
    assert data["revision"] == "rev1"
    assert len(data["cells"]) == 1


def test_edit_add_with_source(monkeypatch):
    from scripts import notebook as nbmod

    nb = nbmod.empty_notebook()
    monkeypatch.setattr(cli.notebook, "read", lambda fid: (nb, "rev1"))
    monkeypatch.setattr(
        cli.notebook, "write", lambda fid, n, expected_revision=None: {"headRevisionId": "rev2"}
    )
    rc, data = _run("edit", "abc", "add", "--source", "print(1)")
    assert rc == 0
    assert data["status"] == "ok"
    assert data["revision"] == "rev2"


def test_edit_requires_source_for_add():
    rc, _ = _run("edit", "abc", "add")
    assert rc != 0


def test_run_requires_cell_or_all():
    rc, _ = _run("run", "abc")
    assert rc != 0


# --- regression: --human must work AFTER the subcommand
# Originally only declared on the top-level parser, which made `colab init --human`
# fail with "unrecognized arguments: --human". Fixed by moving --human onto a
# parents= shared parser used by every subparser.


def test_human_flag_after_subcommand_indents_output():
    rc, out = _run_raw("init", "--human")
    assert rc == 0
    # Indented JSON has newlines; compact JSON does not.
    assert "\n" in out


def test_no_human_flag_emits_compact_json():
    rc, out = _run_raw("init")
    assert rc == 0
    assert "\n" not in out.rstrip()


def test_human_flag_works_on_scope_too():
    rc, out = _run_raw("scope", "--human")
    assert rc == 0
    assert "\n" in out


# --- OAuth scope expansion (PR #3)


def test_scope_default_is_file():
    rc, data = _run("scope")
    assert rc == 0
    assert data["scope"]["oauth"] == "file"


def test_scope_oauth_full_widens_and_emits_note(monkeypatch):
    # Stub set_oauth_scope so we don't actually touch token files.
    from scripts import config as cfg_mod

    def fake_set(scope):
        cfg_mod.update(oauth_scope=scope)
        return cfg_mod.load()

    monkeypatch.setattr("scripts.cli.auth.set_oauth_scope", fake_set)

    rc, data = _run("scope", "--oauth", "full")
    assert rc == 0
    assert data["scope"]["oauth"] == "full"
    assert "re-run /colab-auth" in data.get("note", "").lower()


def test_scope_oauth_unchanged_no_note(monkeypatch):
    """No note emitted when --oauth value matches current config."""
    from scripts import config as cfg_mod

    cfg_mod.update(oauth_scope="file")
    monkeypatch.setattr(
        "scripts.cli.auth.set_oauth_scope",
        lambda s: pytest.fail("set_oauth_scope should not be called when value unchanged"),
    )

    rc, data = _run("scope", "--oauth", "file")
    assert rc == 0
    assert "note" not in data


def test_scope_oauth_invalid_value():
    # argparse rejects at the parser level (choices=...) by raising SystemExit.
    with pytest.raises(SystemExit):
        _run("scope", "--oauth", "readonly")


def test_scope_combines_oauth_and_folder(monkeypatch):
    from scripts import config as cfg_mod

    def fake_set(scope):
        cfg_mod.update(oauth_scope=scope)
        return cfg_mod.load()

    monkeypatch.setattr("scripts.cli.auth.set_oauth_scope", fake_set)

    rc, data = _run("scope", "--oauth", "full", "--folder", "my-stuff")
    assert rc == 0
    assert data["scope"]["oauth"] == "full"
    assert data["scope"]["folder"] == "my-stuff"
    assert data["scope"]["full"] is False  # folder filter still narrow


# --- session routing (PR #4)


def _stub_session(monkeypatch, file_id: str = "abc"):
    """Make session_client.get_active_session return a fake session info."""
    from scripts import session_client

    fake = session_client.SessionInfo(pid=1, port=1, file_id=file_id, runtime="cpu", started_at=0.0)
    monkeypatch.setattr(session_client, "get_active_session", lambda: fake)
    return fake


def test_run_uses_session_when_active(monkeypatch):
    _stub_session(monkeypatch, file_id="abc")
    sent: dict = {}

    def fake_send(cmd, info=None, **kwargs):
        sent["cmd"] = cmd
        sent["kwargs"] = kwargs
        if cmd == "run_cell":
            return {"status": "ok", "result": {"cell_id": kwargs["cell_id"], "status": "ok"}}
        return {}

    monkeypatch.setattr("scripts.cli.session_client.send", fake_send)

    rc, data = _run("run", "abc", "--cell", "c1")
    assert rc == 0
    assert data["via"] == "session"
    assert sent["cmd"] == "run_cell"
    assert sent["kwargs"]["cell_id"] == "c1"


def test_run_falls_back_to_ephemeral_when_no_session(monkeypatch):
    from scripts import session_client

    monkeypatch.setattr(session_client, "get_active_session", lambda: None)
    monkeypatch.setattr(
        "scripts.cli.browser.run_one_cell",
        lambda fid, cid, runtime=None, timeout_sec=600: {"cell_id": cid, "status": "ok"},
    )

    rc, data = _run("run", "abc", "--cell", "c1")
    assert rc == 0
    assert data["via"] == "ephemeral"


def test_run_refuses_when_session_for_different_notebook(monkeypatch):
    _stub_session(monkeypatch, file_id="other-nb")
    rc, _ = _run("run", "my-nb", "--cell", "c1")
    assert rc != 0  # cross-notebook attempt fails


def test_run_all_via_session(monkeypatch):
    _stub_session(monkeypatch, file_id="abc")
    monkeypatch.setattr(
        "scripts.cli.session_client.send",
        lambda cmd, info=None, **kw: {
            "status": "ok",
            "results": [{"cell_id": "c1", "status": "ok"}],
        },
    )
    rc, data = _run("run", "abc", "--all")
    assert rc == 0
    assert data["via"] == "session"
    assert len(data["results"]) == 1


def test_status_when_no_session(monkeypatch):
    from scripts import session_client

    monkeypatch.setattr(session_client, "get_active_session", lambda: None)
    rc, data = _run("status")
    assert rc == 0
    assert data["active"] is False


def test_status_with_active_session(monkeypatch):
    _stub_session(monkeypatch, file_id="abc")
    monkeypatch.setattr("scripts.cli.session_client.ping", lambda info=None: True)
    rc, data = _run("status")
    assert rc == 0
    assert data["active"] is True
    assert data["responsive"] is True
    assert data["session"]["file_id"] == "abc"


def test_close_when_no_session(monkeypatch):
    from scripts import session_client

    monkeypatch.setattr(session_client, "get_active_session", lambda: None)
    rc, data = _run("close")
    assert rc == 0
    assert "no active session" in data.get("note", "")


def test_open_refuses_when_session_already_active(monkeypatch):
    _stub_session(monkeypatch, file_id="other")
    rc, _ = _run("open", "my-nb")
    assert rc != 0  # different notebook → refuse


def test_open_idempotent_when_same_notebook_already_open(monkeypatch):
    _stub_session(monkeypatch, file_id="abc")
    rc, data = _run("open", "abc")
    assert rc == 0
    assert "already active" in data.get("note", "")
