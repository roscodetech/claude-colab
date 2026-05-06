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
    (
        "code",
        (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1, 2, 3], [1, 4, 9])\n"
            "plt.savefig('canary.png')\n"
            "plt.show()\n"
        ),
    ),
    ("code", "raise ValueError('intentional canary error')"),
]


def run() -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": selectors.SCHEMA_VERSION,
        "checks": [],
        "status": "ok",
    }

    file_id = None
    try:
        # 1. Create canary
        meta = drive.create_notebook("claude-colab-selftest")
        file_id = meta["id"]
        nb, rev = notebook.read(file_id)
        # Replace the default empty cell with our canary cells.
        nb.cells = []
        for cell_type, src in CANARY_CELLS:
            notebook.add_cell(nb, src, cell_type=cell_type)
        notebook.write(file_id, nb, expected_revision=rev)
        report["checks"].append({"name": "drive_crud", "ok": True})

        # 2. Run all and collect results
        results = browser.run_all_cells(file_id, runtime="cpu")
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

        # Cell 2: should be marked status=error and error_text non-empty
        c2 = results[2] if len(results) > 2 else {}
        report["checks"].append(
            {
                "name": "error_detection",
                "ok": c2.get("status") == "error" and bool(c2.get("error_text")),
                "got_status": c2.get("status"),
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
