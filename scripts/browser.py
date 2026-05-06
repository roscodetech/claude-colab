"""Playwright-driven Colab automation.

Single notebook at a time — enforced by a file lock. Concurrent calls fail
fast rather than racing two Chromium instances against each other.

Selectors live in selectors.py; if Colab ships a UI change, that's the only
file to edit. Run /colab-selftest after any selector update.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock, Timeout

from . import config, paths as _paths, selectors
from .paths import ensure_home

# Default cell timeout (sec). Colab can pause cells for >10 min on heavy work,
# but the UI shows a "still running" badge — we re-probe rather than give up.
DEFAULT_RUN_TIMEOUT = 600


@dataclass
class RunResult:
    cell_id: str
    status: str  # ok | error | timeout
    stdout: str = ""
    stderr: str = ""
    images: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "images": self.images,
            "duration_ms": self.duration_ms,
            "error_text": self.error_text,
        }


class ColabBusyError(RuntimeError):
    """Raised when another claude-colab session already holds the lock."""


@contextlib.contextmanager
def acquire_lock(timeout: float = 1.0) -> Iterator[None]:
    """File lock for one-notebook-at-a-time. Holds for the lifetime of the with-block."""
    ensure_home()
    lock = FileLock(str(_paths.LOCK_PATH), timeout=timeout)
    try:
        with lock:
            yield
    except Timeout as e:
        raise ColabBusyError(
            "Another claude-colab session is running. Wait or remove "
            f"{_paths.LOCK_PATH} if you're sure nothing's active."
        ) from e


# ---------- Browser session ----------

class ColabSession:
    """Wraps a persistent Chromium context driving a single Colab tab.

    Use as a context manager:
        with ColabSession(file_id="...") as sess:
            sess.connect_runtime("cpu")
            for r in sess.run_all(): ...
    """

    def __init__(self, file_id: str, runtime: str | None = None):
        self.file_id = file_id
        self.runtime = runtime
        self.cfg = config.load()
        self._pw = None
        self._ctx = None
        self.page = None

    def __enter__(self) -> "ColabSession":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(_paths.BROWSER_PROFILE_DIR),
            headless=not self.cfg.get("headed", True),
            channel="chromium",
            viewport={"width": 1400, "height": 900},
        )
        self.page = self._ctx.new_page()
        url = f"https://colab.research.google.com/drive/{self.file_id}"
        self.page.goto(url, wait_until="domcontentloaded")
        # Wait for the cell layout to render before doing anything else.
        self.page.wait_for_selector("div.cell", timeout=30_000)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    # ---------- Runtime ----------

    def connect_runtime(self, kind: str | None = None) -> None:
        """Click Connect; if `kind` is gpu/tpu, change runtime first."""
        kind = (kind or self.runtime or self.cfg.get("default_runtime") or "cpu").lower()

        if kind != "cpu":
            # Open Runtime menu → Change runtime type → pick accelerator → Save
            self.page.click(selectors.RUNTIME_MENU)
            self.page.click(selectors.RUNTIME_CHANGE)
            sel = self.page.locator(selectors.RUNTIME_HARDWARE_SELECT)
            sel.click()
            label = {"gpu": "GPU", "tpu": "TPU"}.get(kind, "GPU")
            self.page.click(f'mwc-list-item:has-text("{label}")')
            self.page.click(selectors.RUNTIME_SAVE)
            self.page.wait_for_timeout(500)

        # Click main Connect button.
        connect = self.page.locator(selectors.CONNECT_BUTTON).first
        with contextlib.suppress(Exception):
            connect.click(timeout=5_000)
        # Wait for the "Connected" state — connect button text changes / disappears.
        self.page.wait_for_function(
            "() => !!document.querySelector('colab-connect-button')?.shadowRoot?.querySelector('[connected]')"
            "|| !!document.querySelector('[aria-label*=\"Connected\"]')",
            timeout=120_000,
        )

    # ---------- Cell execution ----------

    def _cell_locator(self, cell_id: str):
        return self.page.locator(selectors.CELL_BY_ID.format(cell_id=cell_id))

    def run_cell(self, cell_id: str, timeout_sec: int = DEFAULT_RUN_TIMEOUT) -> RunResult:
        cell = self._cell_locator(cell_id)
        cell.scroll_into_view_if_needed()
        # Hover, then click run. Colab's run button is a slot inside the cell.
        cell.hover()
        run = cell.locator(selectors.CELL_RUN_BUTTON).first
        start = time.time()
        run.click()

        # Wait until the cell is no longer marked busy.
        deadline = start + timeout_sec
        while time.time() < deadline:
            classes = cell.get_attribute("class") or ""
            if "running" not in classes and not cell.locator("[busy]").count():
                break
            time.sleep(0.4)
        else:
            return RunResult(cell_id=cell_id, status="timeout", duration_ms=int((time.time() - start) * 1000))

        return self._collect_output(cell_id, cell, start)

    def run_all(self, timeout_sec: int = DEFAULT_RUN_TIMEOUT * 4) -> list[RunResult]:
        # Iterate cells in DOM order — that's the executable order in Colab.
        ids = self.page.eval_on_selector_all(
            "div.cell[data-cell-id]",
            "els => els.map(e => e.getAttribute('data-cell-id'))",
        )
        out: list[RunResult] = []
        for cid in ids:
            out.append(self.run_cell(cid, timeout_sec=timeout_sec))
        return out

    # ---------- Output capture ----------

    def _collect_output(self, cell_id: str, cell, start: float) -> RunResult:
        duration_ms = int((time.time() - start) * 1000)

        # Text output
        text_nodes = cell.locator(selectors.CELL_OUTPUT_TEXT)
        text = "\n".join(text_nodes.all_inner_texts()) if text_nodes.count() else ""

        # Error detection
        err_nodes = cell.locator(selectors.CELL_ERROR)
        error_text = ""
        if err_nodes.count():
            error_text = "\n".join(err_nodes.all_inner_texts())

        # Images
        images: list[str] = []
        if self.cfg.get("save_images", True):
            images = self._save_images(cell_id, cell)

        status = "error" if error_text else "ok"
        return RunResult(
            cell_id=cell_id,
            status=status,
            stdout=text if not error_text else "",
            stderr="",
            error_text=error_text,
            images=images,
            duration_ms=duration_ms,
        )

    def _save_images(self, cell_id: str, cell) -> list[str]:
        """Pull <img> src blobs out of a cell's output area, save as PNG."""
        out_dir = _paths.RUNS_DIR / self.file_id / cell_id
        out_dir.mkdir(parents=True, exist_ok=True)

        srcs = cell.locator(selectors.CELL_OUTPUT_IMAGE).evaluate_all(
            "els => els.map(e => e.src)"
        )
        saved: list[str] = []
        for i, src in enumerate(srcs):
            if not src:
                continue
            data = _decode_img_src(src)
            if data is None:
                continue
            path = out_dir / f"{int(time.time())}_{i}.png"
            path.write_bytes(data)
            saved.append(str(path))
        return saved


def _decode_img_src(src: str) -> bytes | None:
    """Handle data: URIs (most common in Colab plot output) and skip http(s)."""
    m = re.match(r"data:image/[^;]+;base64,(.*)", src)
    if not m:
        return None
    try:
        return base64.b64decode(m.group(1))
    except Exception:
        return None


# ---------- Public entrypoints ----------

def run_one_cell(file_id: str, cell_id: str, runtime: str | None = None, timeout_sec: int = DEFAULT_RUN_TIMEOUT) -> dict[str, Any]:
    with acquire_lock():
        with ColabSession(file_id, runtime=runtime) as sess:
            sess.connect_runtime(runtime)
            return sess.run_cell(cell_id, timeout_sec=timeout_sec).to_dict()


def run_all_cells(file_id: str, runtime: str | None = None) -> list[dict[str, Any]]:
    with acquire_lock():
        with ColabSession(file_id, runtime=runtime) as sess:
            sess.connect_runtime(runtime)
            return [r.to_dict() for r in sess.run_all()]


def open_only(file_id: str) -> dict[str, Any]:
    """Open the notebook in a headed browser and leave it open. For /colab-open."""
    # No lock — opening doesn't run cells, user might want to inspect alongside other work.
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(_paths.BROWSER_PROFILE_DIR),
        headless=False,
        channel="chromium",
        viewport={"width": 1400, "height": 900},
    )
    page = ctx.new_page()
    page.goto(f"https://colab.research.google.com/drive/{file_id}")
    return {"status": "opened", "file_id": file_id, "url": page.url}
