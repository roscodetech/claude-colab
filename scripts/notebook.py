"""Cell CRUD over .ipynb JSON via nbformat.

Cells are addressed by stable nbformat 4.5 ids. Index addressing supported as
a convenience but discouraged — concurrent edits change indices.

All mutators return the modified Notebook so callers can chain. Whether to
write back to Drive is the caller's call (we don't want hidden network I/O).
"""

from __future__ import annotations

from typing import Any

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from . import drive

NBFORMAT_VERSION = 4
NBFORMAT_MINOR = 5  # required for stable cell ids


# ---------- Construction ----------

def empty_notebook() -> nbformat.NotebookNode:
    nb = new_notebook()
    nb.nbformat = NBFORMAT_VERSION
    nb.nbformat_minor = NBFORMAT_MINOR
    nb.metadata.setdefault(
        "kernelspec",
        {"name": "python3", "display_name": "Python 3"},
    )
    nb.metadata.setdefault("colab", {"provenance": []})
    # Start with one empty code cell — matches Colab's default.
    nb.cells.append(new_code_cell(source=""))
    return nb


def empty_notebook_bytes() -> bytes:
    return nbformat.writes(empty_notebook()).encode("utf-8")


# ---------- Drive round-trip ----------

def read(file_id: str) -> tuple[nbformat.NotebookNode, str | None]:
    """Fetch from Drive and parse. Returns (notebook, head_revision_id)."""
    raw = drive.get_notebook_bytes(file_id)
    nb = nbformat.reads(raw.decode("utf-8"), as_version=NBFORMAT_VERSION)
    # Force minor version 5 so we always have stable ids.
    nb.nbformat_minor = NBFORMAT_MINOR
    meta = drive.get_metadata(file_id)
    return nb, meta.get("headRevisionId")


def write(file_id: str, nb: nbformat.NotebookNode, expected_revision: str | None = None) -> dict[str, Any]:
    """Serialize and upload. Pass expected_revision for optimistic locking."""
    payload = nbformat.writes(nb).encode("utf-8")
    return drive.update_notebook(file_id, payload, expected_revision=expected_revision)


# ---------- Cell ops ----------

def _find_idx(nb: nbformat.NotebookNode, cell_ref: str | int) -> int:
    """Resolve a cell_id (str) or index (int) to an integer index."""
    if isinstance(cell_ref, int):
        if cell_ref < 0 or cell_ref >= len(nb.cells):
            raise IndexError(f"cell index {cell_ref} out of range (len={len(nb.cells)})")
        return cell_ref
    for i, cell in enumerate(nb.cells):
        if cell.get("id") == cell_ref:
            return i
    raise KeyError(f"cell id not found: {cell_ref!r}")


def get_cell(nb: nbformat.NotebookNode, cell_ref: str | int) -> dict[str, Any]:
    return dict(nb.cells[_find_idx(nb, cell_ref)])


def add_cell(
    nb: nbformat.NotebookNode,
    source: str,
    cell_type: str = "code",
    after: str | int | None = None,
) -> str:
    """Insert a cell. Returns the new cell's id.

    `after` = None → append. Otherwise inserts after the referenced cell.
    """
    if cell_type == "code":
        cell = new_code_cell(source=source)
    elif cell_type == "markdown":
        cell = new_markdown_cell(source=source)
    else:
        raise ValueError(f"unsupported cell_type: {cell_type}")

    if after is None:
        nb.cells.append(cell)
    else:
        idx = _find_idx(nb, after) + 1
        nb.cells.insert(idx, cell)
    return cell["id"]


def edit_cell(nb: nbformat.NotebookNode, cell_ref: str | int, source: str) -> str:
    """Replace cell source. Returns the cell id."""
    idx = _find_idx(nb, cell_ref)
    nb.cells[idx]["source"] = source
    # Editing invalidates prior outputs.
    if nb.cells[idx].get("cell_type") == "code":
        nb.cells[idx]["outputs"] = []
        nb.cells[idx]["execution_count"] = None
    return nb.cells[idx]["id"]


def delete_cell(nb: nbformat.NotebookNode, cell_ref: str | int) -> str:
    idx = _find_idx(nb, cell_ref)
    cell_id = nb.cells[idx].get("id", "")
    del nb.cells[idx]
    return cell_id


def reorder(nb: nbformat.NotebookNode, cell_ids: list[str]) -> None:
    """Reorder cells to match the given id list. All ids must be present."""
    by_id = {c["id"]: c for c in nb.cells}
    if set(by_id) != set(cell_ids):
        missing = set(by_id) - set(cell_ids)
        extra = set(cell_ids) - set(by_id)
        raise ValueError(f"reorder mismatch: missing={missing}, extra={extra}")
    nb.cells = [by_id[i] for i in cell_ids]


# ---------- Inspection ----------

def summarize(nb: nbformat.NotebookNode, source_lines: int = 2) -> list[dict[str, Any]]:
    """Compact representation for agent context — id, type, first N source lines."""
    out = []
    for i, cell in enumerate(nb.cells):
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        head = "\n".join(src.splitlines()[:source_lines])
        out.append({
            "idx": i,
            "id": cell.get("id"),
            "type": cell.get("cell_type"),
            "source_head": head,
            "has_output": bool(cell.get("outputs")) if cell.get("cell_type") == "code" else False,
            "execution_count": cell.get("execution_count"),
        })
    return out


def cell_outputs_text(nb: nbformat.NotebookNode, cell_ref: str | int) -> str:
    """Concatenate text-bearing outputs of a cell. Useful for /colab-output."""
    idx = _find_idx(nb, cell_ref)
    cell = nb.cells[idx]
    if cell.get("cell_type") != "code":
        return ""
    parts: list[str] = []
    for out in cell.get("outputs", []):
        t = out.get("output_type")
        if t == "stream":
            parts.append(out.get("text", ""))
        elif t in ("execute_result", "display_data"):
            data = out.get("data", {})
            if "text/plain" in data:
                parts.append(data["text/plain"])
        elif t == "error":
            parts.append("\n".join(out.get("traceback", [])))
    return "".join(parts)
