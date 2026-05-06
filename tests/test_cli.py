"""CLI dispatch — argparse routing + JSON output shape.

We mock the underlying layers so we test cli.py's own logic, not transitively
re-test drive/notebook/browser.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

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
