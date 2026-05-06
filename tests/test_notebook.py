"""Cell CRUD round-trip on the nbformat layer (no Drive)."""

from __future__ import annotations

import nbformat
import pytest

from scripts import notebook


def test_empty_notebook_has_one_code_cell():
    nb = notebook.empty_notebook()
    assert nb.nbformat == 4
    assert nb.nbformat_minor == 5
    assert len(nb.cells) == 1
    assert nb.cells[0]["cell_type"] == "code"
    assert nb.cells[0].get("id")  # stable id present


def test_add_cell_returns_id_and_appends():
    nb = notebook.empty_notebook()
    cid = notebook.add_cell(nb, "print('hi')", cell_type="code")
    assert isinstance(cid, str) and cid
    assert len(nb.cells) == 2
    assert nb.cells[-1]["id"] == cid
    assert "print('hi')" in nb.cells[-1]["source"]


def test_add_cell_after_specific_id():
    nb = notebook.empty_notebook()
    first = nb.cells[0]["id"]
    inserted = notebook.add_cell(nb, "x = 1", after=first)
    appended = notebook.add_cell(nb, "y = 2")  # default = end
    assert nb.cells[1]["id"] == inserted
    assert nb.cells[2]["id"] == appended


def test_edit_cell_clears_outputs():
    nb = notebook.empty_notebook()
    cid = notebook.add_cell(nb, "1+1")
    # Simulate a previously-run cell
    nb.cells[-1]["outputs"] = [{"output_type": "stream", "name": "stdout", "text": "2"}]
    nb.cells[-1]["execution_count"] = 1

    notebook.edit_cell(nb, cid, "2+2")
    assert nb.cells[-1]["source"] == "2+2"
    assert nb.cells[-1]["outputs"] == []
    assert nb.cells[-1]["execution_count"] is None


def test_delete_cell_by_id_and_index():
    nb = notebook.empty_notebook()
    a = notebook.add_cell(nb, "a")
    notebook.add_cell(nb, "b")
    assert len(nb.cells) == 3

    notebook.delete_cell(nb, a)
    assert len(nb.cells) == 2
    assert all(c["id"] != a for c in nb.cells)

    notebook.delete_cell(nb, 0)  # by index
    assert len(nb.cells) == 1


def test_reorder_full_permutation():
    nb = notebook.empty_notebook()
    a = nb.cells[0]["id"]
    b = notebook.add_cell(nb, "b")
    c = notebook.add_cell(nb, "c")

    notebook.reorder(nb, [c, a, b])
    assert [cell["id"] for cell in nb.cells] == [c, a, b]


def test_reorder_rejects_partial_id_list():
    nb = notebook.empty_notebook()
    a = nb.cells[0]["id"]
    notebook.add_cell(nb, "b")
    with pytest.raises(ValueError):
        notebook.reorder(nb, [a])  # missing the second cell


def test_summarize_compact_view():
    nb = notebook.empty_notebook()
    notebook.edit_cell(nb, 0, "import pandas as pd\nimport numpy as np\n# extra")
    notebook.add_cell(nb, "## Section header", cell_type="markdown")

    s = notebook.summarize(nb)
    assert len(s) == 2
    assert s[0]["type"] == "code"
    assert "pandas" in s[0]["source_head"]
    assert "extra" not in s[0]["source_head"]  # source_lines=2 default
    assert s[1]["type"] == "markdown"


def test_cell_outputs_text_concatenates_streams():
    nb = notebook.empty_notebook()
    cid = nb.cells[0]["id"]
    nb.cells[0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": "hello "},
        {"output_type": "execute_result", "data": {"text/plain": "world"}},
    ]
    text = notebook.cell_outputs_text(nb, cid)
    assert "hello" in text and "world" in text


def test_unknown_cell_id_raises():
    nb = notebook.empty_notebook()
    with pytest.raises(KeyError):
        notebook.get_cell(nb, "no-such-id")


def test_round_trip_via_nbformat_serialization():
    nb = notebook.empty_notebook()
    notebook.add_cell(nb, "x = 1")
    notebook.add_cell(nb, "## md", cell_type="markdown")

    serialized = nbformat.writes(nb)
    nb2 = nbformat.reads(serialized, as_version=4)
    assert len(nb2.cells) == 3
    assert nb2.cells[0]["cell_type"] == "code"
    assert nb2.cells[2]["cell_type"] == "markdown"
