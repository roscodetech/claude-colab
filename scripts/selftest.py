"""Canary notebook smoke test.

Creates a throwaway notebook with three cells (print, plot, deliberate error),
runs it, and reports which selectors produced expected output. Helps catch
Colab UI changes before they bite real workflows.

Cleanup: notebook is hard-deleted at the end unless --keep is passed (handled
by the CLI flag — selftest.run itself always deletes).
"""

from __future__ import annotations

import contextlib
from typing import Any

from . import browser, drive, notebook, selectors

CANARY_CELLS = [
    ("code", "print('hello from claude-colab')"),
    # Don't pin matplotlib backend — Colab's inline produces the <img> we need.
    (
        "code",
        ("import matplotlib.pyplot as plt\nplt.plot([1, 2, 3], [1, 4, 9])\nplt.show()\n"),
    ),
    # DataFrame display — exercises rich-text capture from the iframe (HTML
    # table). If our selectors miss this, rich_text_capture check fails.
    (
        "code",
        ("import pandas as pd\ndf = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})\ndf\n"),
    ),
    ("code", "raise ValueError('intentional canary error')"),
]


def run(runtime: str = "cpu") -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": selectors.SCHEMA_VERSION,
        "runtime": runtime,
        "checks": [],
        "status": "ok",
    }

    cells = list(CANARY_CELLS)
    if runtime != "cpu":
        # Append a GPU/TPU verification cell only when --runtime is non-cpu —
        # consumes Colab quota; keep CPU runs cheap.
        cells.append(
            (
                "code",
                (
                    "import torch\n"
                    "print('cuda_available:', torch.cuda.is_available())\n"
                    "print('device:', torch.cuda.get_device_name(0) "
                    "if torch.cuda.is_available() else 'no GPU')\n"
                ),
            )
        )

    file_id = None
    try:
        # 1. Create canary
        meta = drive.create_notebook("claude-colab-selftest")
        file_id = meta["id"]
        nb, rev = notebook.read(file_id)
        # Replace the default empty cell with our canary cells.
        nb.cells = []
        for cell_type, src in cells:
            notebook.add_cell(nb, src, cell_type=cell_type)
        notebook.write(file_id, nb, expected_revision=rev)
        report["checks"].append({"name": "drive_crud", "ok": True})

        # 2. Run all and collect results
        results = browser.run_all_cells(file_id, runtime=runtime)
        report["checks"].append({"name": "browser_run_all", "ok": True, "n_cells": len(results)})

        # Cell 0: should have stdout containing 'hello from claude-colab'
        c0 = results[0] if len(results) > 0 else {}
        report["checks"].append(
            {
                "name": "stdout_capture",
                "ok": "hello from claude-colab" in (c0.get("stdout") or ""),
                "got": (c0.get("stdout") or "")[:80],
            }
        )

        # Cell 1: should have at least one image saved
        c1 = results[1] if len(results) > 1 else {}
        report["checks"].append(
            {
                "name": "image_capture",
                "ok": bool(c1.get("images")),
                "n_images": len(c1.get("images") or []),
            }
        )

        # Cell 2: DataFrame display — rich text from iframe should contain 'a'
        # and 'b' (column headers) and the row values.
        c2 = results[2] if len(results) > 2 else {}
        c2_text = (c2.get("stdout") or "").lower()
        report["checks"].append(
            {
                "name": "rich_text_capture",
                "ok": "a" in c2_text and "b" in c2_text and "x" in c2_text,
                "got": (c2.get("stdout") or "")[:120],
            }
        )

        # Cell 3: should be marked status=error and error_text non-empty
        c3 = results[3] if len(results) > 3 else {}
        report["checks"].append(
            {
                "name": "error_detection",
                "ok": c3.get("status") == "error" and bool(c3.get("error_text")),
                "got_status": c3.get("status"),
            }
        )

        # Optional GPU/TPU verification — appended when caller passed --runtime.
        if runtime != "cpu":
            c4 = results[4] if len(results) > 4 else {}
            stdout = c4.get("stdout") or ""
            ok = "cuda_available: True" in stdout
            report["checks"].append(
                {
                    "name": f"{runtime}_runtime_active",
                    "ok": ok,
                    "got": stdout[:160],
                }
            )
    except Exception as e:
        report["status"] = "error"
        report["error"] = str(e)
    finally:
        if file_id:
            # Don't shadow the real failure if cleanup also fails.
            with contextlib.suppress(Exception):
                drive.delete_notebook(file_id, hard=True)

    # Final status reflects whether all checks passed
    if report["status"] == "ok" and not all(c.get("ok") for c in report["checks"]):
        report["status"] = "selectors_drifted"
    return report
