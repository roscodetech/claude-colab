"""Playwright-driven Colab automation.

Single notebook at a time — enforced by a file lock. Concurrent calls fail
fast rather than racing two Chromium instances against each other.

Selectors live in selectors.py; if Colab ships a UI change, that's the only
file to edit. Run /colab-selftest after any selector update.
"""

from __future__ import annotations

import base64
import contextlib
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from filelock import FileLock, Timeout

from . import config, selectors
from . import paths as _paths
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

    def __enter__(self) -> ColabSession:
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
        self.page.wait_for_selector(selectors.CELL_LIST, timeout=30_000)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._disconnect_runtime_best_effort()
        finally:
            try:
                if self._ctx:
                    self._ctx.close()
            finally:
                if self._pw:
                    self._pw.stop()

    def _disconnect_runtime_best_effort(self) -> None:
        """Tell Colab to release the runtime before tearing the browser down.

        `_ctx.close()` alone is interpreted as a temporary disconnect; the
        server-side runtime keeps running for ~12 h waiting for a
        reconnection, which burns one of the (very tight) Pro+
        concurrent-session slots. Sending the explicit "Disconnect and
        delete runtime" command frees the slot immediately.

        Always attempts the menu sequence rather than gating on a probe —
        the menu item is a no-op when no runtime is attached (Colab
        either omits it from the menu or it silently fails), so over-
        attempting is harmless and we avoid every false-negative the
        probe could hand us. Each step writes its outcome to session.log
        so a maintainer can audit teardowns.
        """
        page = self.page
        if page is None:
            self._log_lifecycle("disconnect: no page, skipping")
            return
        clicked_menu = False
        clicked_disconnect = False
        confirmed = False
        try:
            page.locator(selectors.RUNTIME_MENU_CLASS).filter(
                has_text="Runtime"
            ).first.click(timeout=2_500)
            clicked_menu = True
            # Menu item is only present when a runtime is attached. If not,
            # locator times out at 2 s and we exit cleanly via the except.
            page.locator('text="Disconnect and delete runtime"').first.click(
                timeout=2_000
            )
            clicked_disconnect = True
            # Confirmation dialog: "Are you sure you want to disconnect..."
            page.locator(
                'mwc-dialog[open] md-text-button[slot="primaryAction"], '
                'mwc-dialog[open] md-text-button[dialogaction="ok"]'
            ).first.click(timeout=2_000)
            confirmed = True
            page.wait_for_timeout(800)
        except Exception as e:
            self._log_lifecycle(
                f"disconnect: stopped at "
                f"menu={clicked_menu} item={clicked_disconnect} confirm={confirmed} "
                f"({type(e).__name__}: {str(e)[:120]})"
            )
            # Click body to close any half-open menu so it doesn't block
            # the next session's interactions on this profile.
            with contextlib.suppress(Exception):
                page.locator("body").click(timeout=1_000)
            return
        self._log_lifecycle("disconnect: ok (runtime released)")

    def _log_lifecycle(self, msg: str) -> None:
        """Append a lifecycle event to ~/.claude-colab/session.log so daemon
        teardowns are observable from the same surface as run-time logs."""
        from .paths import SESSION_LOG_PATH

        with contextlib.suppress(Exception), SESSION_LOG_PATH.open(
            "a", encoding="utf-8"
        ) as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

    # ---------- Runtime liveness probe ----------

    def attached_runtime_kind(self) -> str | None:
        """Return the accelerator kind ('cpu' / 'gpu' / 'tpu') currently
        attached to the notebook, or None if no runtime is attached.

        Detection is DOM-driven and cheap: Colab's runtime status indicator
        in the top-right exposes its state via the connect button's
        aria-label. Fresh notebook → "Connect to a hosted runtime"; warm
        runtime → "Connected to Python 3 (..., A100 GPU)" or similar.

        Best-effort. Returns None on any probe failure so callers fall back
        to the explicit Change runtime + Connect flow.
        """
        if self.page is None:
            return None
        try:
            label = self.page.locator(selectors.CONNECT_BUTTON).first.get_attribute(
                "aria-label", timeout=2_000
            ) or ""
        except Exception:
            return None
        low = label.lower()
        # The disconnected state has "connect to" with no past-tense ed —
        # critically distinct from "connected to". Use a word-boundary
        # check so the "connect to" substring of "connected to" doesn't
        # false-positive as disconnected.
        if re.search(r"\bconnect\s+to\b", low) and "connected" not in low:
            return None
        if "connected" not in low:
            # Unknown state (label changed shape) — refuse to guess.
            return None
        # Map detected accelerator. Colab labels the line as "Python 3,
        # A100 GPU, High-RAM" or similar; substring match against the
        # accelerator priority lists tells us the kind.
        for variant in selectors.RUNTIME_HARDWARE_GPU_PRIORITY:
            if variant.lower() in low:
                return "gpu"
        for variant in selectors.RUNTIME_HARDWARE_TPU_PRIORITY:
            if variant.lower() in low:
                return "tpu"
        if "gpu" in low:
            return "gpu"
        if "tpu" in low:
            return "tpu"
        return "cpu"

    def connect_runtime(self, kind: str | None = None) -> None:
        """Best-effort: reuse an attached runtime if compatible, else Change
        runtime type → Save → Connect.

        Past behaviour was to *always* open Change runtime type when kind !=
        cpu, which caused Colab to spawn a fresh runtime even when a
        compatible one was already attached. Each spawned-but-then-abandoned
        runtime sat as a 12 h zombie holding a Pro+ concurrent-session slot,
        and a few rapid /colab-open cycles were enough to fully starve the
        account. The probe-first-then-spawn flow below avoids that whenever
        Colab has already wired a runtime to the notebook for this account.

        Does NOT wait for a confirmed "connected" state. Past attempts at that
        relied on shadow-DOM probes that break every time Colab ships UI
        changes (caught by /colab-selftest 2026-05-07). Colab auto-connects
        when you click Run on a cell anyway, so we let run_cell absorb any
        remaining connection time via its own per-cell timeout.
        """
        kind = (kind or self.runtime or self.cfg.get("default_runtime") or "cpu").lower()

        # Reuse path: if a compatible runtime is already attached, skip
        # the Change-runtime-type dance entirely. This is the single most
        # impactful fix for the runtime-leak failure mode (#runtime-leak).
        attached = self.attached_runtime_kind()
        if attached is not None and (kind == "cpu" or attached == kind):
            # Already connected to the right kind — nothing to do.
            return
        if attached is not None and attached != kind:
            # Wrong kind attached — we'll proceed into Change runtime type
            # below, which will prompt a "Discard current runtime?" warning
            # that the dialog flow already handles.
            pass

        if kind != "cpu":
            # Change accelerator before connecting — switching after forces restart.
            # Runtime menu uses goog-menu-button with whitespace-padded labels;
            # locator+filter handles that better than CSS :text-is.
            self.page.locator(selectors.RUNTIME_MENU_CLASS).filter(has_text="Runtime").first.click()
            self.page.click(selectors.RUNTIME_CHANGE)

            # Modern Colab dialog (probed 2026-05-08): hardware picker is a
            # set of mwc-radio buttons inside a custom-element shadow DOM.
            # The mwc-radios themselves have empty aria-label; the visible
            # text "A100 GPU" / "CPU" / etc. lives on a sibling label. So we
            # can't use a CSS attribute selector — get_by_label() walks the
            # accessibility tree and pairs label text to the labelled element
            # across shadow boundaries. Try a priority list of accelerator
            # variants and click the first one Colab is offering this user.
            priority = (
                selectors.RUNTIME_HARDWARE_GPU_PRIORITY
                if kind == "gpu"
                else selectors.RUNTIME_HARDWARE_TPU_PRIORITY
                if kind == "tpu"
                else [selectors.RUNTIME_HARDWARE_CPU]
            )
            picked: str | None = None
            try:
                for label in priority:
                    radio = self.page.get_by_label(label, exact=True)
                    if radio.count() == 0:
                        continue
                    try:
                        radio.first.click(timeout=2_500)
                        picked = label
                        break
                    except Exception:
                        # Radio exists but isn't clickable (disabled / off-quota);
                        # try the next priority.
                        continue
                if picked is None:
                    raise RuntimeError(
                        f"no {kind!r} accelerator available — "
                        f"none of {priority} resolved via get_by_label()"
                    )
                self.page.click(selectors.RUNTIME_SAVE, timeout=5_000)
                # If there's an existing connected runtime, Colab pops a
                # second "Discard current runtime?" warning dialog and the
                # original Save click never lands. Confirm it explicitly.
                self.page.wait_for_timeout(800)
                warning = self.page.locator(
                    'mwc-dialog.dismiss-runtime-warning[open]'
                )
                if warning.count():
                    # Primary action button text varies by Colab build
                    # ("Yes", "Discard", "Continue"). Try the primaryAction
                    # slot first, then fall back to text.
                    confirm = warning.locator(
                        'md-text-button[slot="primaryAction"], '
                        'md-text-button[dialogaction="ok"], '
                        'button:has-text("Yes"), button:has-text("Discard")'
                    ).first
                    if confirm.count():
                        confirm.click(timeout=3_000)
                        self.page.wait_for_timeout(500)
            except Exception as e:
                # Cancel the dialog so it doesn't sit blocking pointer events.
                with contextlib.suppress(Exception):
                    self.page.locator(
                        'mwc-dialog.change-runtime-type md-text-button:has-text("Cancel")'
                    ).first.click(timeout=2_000)
                raise RuntimeError(
                    f"Runtime-type dialog interaction failed ({e}). "
                    "Run scripts/probe_runtime_dialog2.py to re-probe selectors."
                ) from e

        # Click Connect; suppress if already connected (button gone).
        with contextlib.suppress(Exception):
            self.page.locator(selectors.CONNECT_BUTTON).first.click(timeout=5_000)
        # Brief settle so the click registers before run_cell starts.
        self.page.wait_for_timeout(2_000)

    # ---------- Modal dialogs & runtime state ----------

    def dismiss_blocking_dialogs(self) -> int:
        """Force-close any open mwc-dialog. Colab pops these for runtime errors,
        "notebook modified externally" warnings, and "restart session?" prompts;
        each one intercepts pointer events on every cell — every subsequent
        hover then dies at the 30s Playwright default with no useful diagnostic.

        Returns the count dismissed. Best-effort — never raises.
        """
        if self.page is None:
            return 0
        try:
            # Use Locator.evaluate rather than Page.evaluate: the latter is
            # bound to the greenlet that created the page and raises
            # `greenlet.error: Cannot switch to a different thread` if the
            # daemon's connection-thread tries to drive it. Locator-rooted
            # ops are thread-tolerant.
            n = self.page.locator("body").evaluate(
                "_ => { const ds = document.querySelectorAll('mwc-dialog[open]');"
                " for (const d of ds) { d.removeAttribute('open'); d.style.display='none'; }"
                " return ds.length; }"
            )
            return int(n)
        except Exception:
            return 0

    def kernel_restart_pending(self) -> bool:
        """True when Colab is showing the post-pip-install "Restart session?"
        prompt. Colab silently restarts the kernel after some pip installs
        (e.g. when the new package conflicts with an already-imported module),
        which clears every variable defined upstream — cells further down the
        notebook then NameError on names they expect to exist. Detect the
        prompt so callers can decide to accept-and-rerun upstream cells.

        Best-effort DOM probe — never raises. Routed through a Locator to
        stay tolerant of cross-thread calls (see dismiss_blocking_dialogs).
        """
        if self.page is None:
            return False
        try:
            return bool(
                self.page.locator("body").evaluate(
                    "el => {"
                    "  const txt = el.innerText || '';"
                    "  return /Restart session/i.test(txt) || "
                    "         /You must restart the runtime/i.test(txt) || "
                    "         /WARNING: The following packages were previously imported/i.test(txt);"
                    "}"
                )
            )
        except Exception:
            return False

    def accept_kernel_restart(self) -> bool:
        """Click Colab's "Restart session" button if visible. Returns True
        if a button was clicked. Use after `kernel_restart_pending()` returns
        True to commit the restart (and lose kernel state) rather than
        leaving the prompt blocking other cells."""
        if self.page is None:
            return False
        try:
            # Buttons in the prompt vary by Colab version; try the common
            # labels in priority order.
            for label in ("Restart session", "Restart runtime", "RESTART SESSION"):
                btn = self.page.locator(f'button:has-text("{label}")').first
                if btn.count():
                    btn.click(timeout=5_000)
                    self.page.wait_for_timeout(1_500)
                    return True
        except Exception:
            pass
        return False

    # ---------- Cell execution ----------

    def _cell_locator(self, cell_id: str):
        return self.page.locator(selectors.CELL_BY_ID.format(cell_id=cell_id))

    def _cell_is_busy(self, cell) -> bool:
        classes = cell.get_attribute("class") or ""
        return "running" in classes or cell.locator("[busy]").count() > 0

    def run_cell(self, cell_id: str, timeout_sec: int = DEFAULT_RUN_TIMEOUT) -> RunResult:
        # Modals would block hover/click silently for 30s — clear them first.
        self.dismiss_blocking_dialogs()

        cell = self._cell_locator(cell_id)
        cell.scroll_into_view_if_needed()
        # Hover, then click run. Colab's run button is a slot inside the cell.
        cell.hover()
        run = cell.locator(selectors.CELL_RUN_BUTTON).first
        start = time.time()
        run.click()

        # Two-phase wait:
        # 1. Wait until we observe the cell entered a running state (or until
        #    `start_grace` elapses — runtime startup can delay the running mark).
        # 2. Then wait until it leaves running.
        # Without phase 1, an unstarted cell would `break` immediately and we'd
        # collect empty output before the cell actually ran.
        deadline = start + timeout_sec
        start_grace = start + 60  # give Colab up to 60s to mark the cell running
        saw_running = False

        while time.time() < deadline:
            is_running = self._cell_is_busy(cell)
            if is_running:
                saw_running = True
            elif saw_running:
                break  # Was running, now isn't → done.
            elif time.time() > start_grace:
                # Grace expired and we never saw it run. Either the cell ran
                # too fast for our 0.4s poll, or Colab silently rejected it.
                # Either way, collecting output is the right move — if there's
                # nothing, status will reflect that.
                break
            time.sleep(0.4)
        else:
            return RunResult(
                cell_id=cell_id, status="timeout", duration_ms=int((time.time() - start) * 1000)
            )

        return self._collect_output(cell_id, cell, start)

    def run_all(self, timeout_sec: int = DEFAULT_RUN_TIMEOUT * 4) -> list[RunResult]:
        # Iterate cells in DOM order — that's the executable order in Colab.
        # The DOM id is `cell-<nbformat-id>`; strip the prefix.
        # Skip markdown cells: they have no run button, so clicking would hang
        # for the locator timeout. Colab tags them via a child `marked-element`
        # /`paper-icon-button[aria-label*="Run"]` absence; simplest reliable
        # filter is the presence of a run button on the cell.
        ids = self.page.eval_on_selector_all(
            selectors.CELL_LIST,
            # Colab tags code cells with class `code` and markdown cells with `text`.
            # Run button is sometimes shadow-DOM / lazy-rendered, so don't gate on it.
            "els => els.filter(e => e.classList.contains('code'))"
            ".map(e => (e.getAttribute('id') || '').replace(/^cell-/, '')).filter(Boolean)",
        )
        out: list[RunResult] = []
        for cid in ids:
            out.append(self.run_cell(cid, timeout_sec=timeout_sec))
        return out

    def run_all_native_events(
        self,
        timeout_sec: int = 3600,
        accept_kernel_restart: bool = True,
    ):
        """Generator: trigger Colab's Run All (Ctrl+F9), yield one state dict
        per change, return on natural completion. Single-threaded — every
        Playwright call happens in the caller's thread, which lets the daemon
        relay events over TCP without spawning a worker thread (Playwright's
        sync API is bound to the greenlet that created its objects).

        Yielded shape:
            {"running": int, "queued": int, "total": int,
             "kernel_restart_pending": bool, "kernel_restarted": bool}

        accept_kernel_restart: when True (default), click "Restart session"
        whenever Colab pops the prompt and re-issue Ctrl+F9 from the top.
        Without this, downstream cells NameError on cleared kernel state
        after a silent pip-install-triggered restart.

        Raises TimeoutError if the queue never drains within timeout_sec.
        """
        self.dismiss_blocking_dialogs()
        # Focus the notebook + send Ctrl+F9. Routing through Locator keeps
        # us thread-tolerant: page.click / page.keyboard.press are bound to
        # the greenlet that created the Page object, but Locator-rooted ops
        # work cross-thread (which the daemon needs since each command runs
        # on a per-connection thread).
        body = self.page.locator("body")
        body.click()
        body.press("Control+F9")

        deadline = time.time() + timeout_sec
        last_state: dict[str, Any] | None = None
        first_seen_running = False
        kernel_restarted_once = False

        while time.time() < deadline:
            time.sleep(2.0)
            self.dismiss_blocking_dialogs()
            restart_pending = self.kernel_restart_pending()
            # Accept once and re-issue Run All from the top so cells
            # downstream don't NameError on cleared state.
            if (
                restart_pending
                and accept_kernel_restart
                and not kernel_restarted_once
                and self.accept_kernel_restart()
            ):
                kernel_restarted_once = True
                self.page.wait_for_timeout(2_000)
                body.click()
                body.press("Control+F9")
                first_seen_running = False
                last_state = None
                continue
            state = body.evaluate(
                "_ => ({"
                "  running: document.querySelectorAll('.cell.code.running').length,"
                "  queued: document.querySelectorAll('.cell.code.pending,.cell.code.queued').length,"
                "  total: document.querySelectorAll('.cell.code').length,"
                "})"
            )
            state["kernel_restart_pending"] = restart_pending
            state["kernel_restarted"] = kernel_restarted_once
            if state != last_state:
                yield state
                last_state = state
            if state["running"] > 0:
                first_seen_running = True
            elif first_seen_running and state["queued"] == 0:
                return
        raise TimeoutError(f"run_all_native timed out after {timeout_sec}s")

    def run_all_native(
        self,
        timeout_sec: int = 3600,
        on_state: Any = None,
        accept_kernel_restart: bool = True,
    ) -> dict[str, Any] | None:
        """Synchronous wrapper around run_all_native_events: drains the
        generator and returns the final state dict. on_state, if given, is
        invoked with each state change."""
        final: dict[str, Any] | None = None
        for state in self.run_all_native_events(
            timeout_sec=timeout_sec, accept_kernel_restart=accept_kernel_restart
        ):
            final = state
            if on_state is not None:
                with contextlib.suppress(Exception):
                    on_state(state)
        return final

    # ---------- Output capture ----------

    def _collect_output(self, cell_id: str, cell, start: float) -> RunResult:
        """Collect output from BOTH the parent cell DOM and any nested iframes.

        Colab splits cell output across two surfaces:
        - Parent DOM `.stream.output_text` → plain stdout (print, etc.)
        - Per-cell `<iframe>` from *.colab.googleusercontent.com/outputframe.html
          → rich output (errors, plot images, DataFrame HTML tables, formatted
          repr's of objects, anything with a non-text/plain MIME type).

        We collect from both. If parent stream is empty (no print) we fall
        back to iframe rich text, which catches DataFrames, dict/list reprs,
        and other "execute_result" output that ipykernel routed via display_data.
        """
        duration_ms = int((time.time() - start) * 1000)

        # Parent-DOM stream text (plain stdout).
        parent_text_nodes = cell.locator(selectors.CELL_OUTPUT_TEXT)
        parent_text = (
            "\n".join(parent_text_nodes.all_inner_texts()) if parent_text_nodes.count() else ""
        )

        # Drill into the iframe — error text, image srcs, rich text.
        error_text, iframe_imgs, iframe_rich_text = self._read_iframe_outputs(cell)

        # Parent-DOM error fallback (older schemas / edge cases).
        if not error_text:
            err_nodes = cell.locator(selectors.CELL_ERROR)
            if err_nodes.count():
                error_text = "\n".join(err_nodes.all_inner_texts())

        # Output text: prefer stream; fall back to rich. Concatenate when both
        # have distinct content (rare — usually only one surface produces text).
        text = _merge_output_text(parent_text, iframe_rich_text)

        images: list[str] = []
        if self.cfg.get("save_images", True):
            # Combine parent-DOM imgs (rare) with iframe imgs (common).
            parent_imgs = cell.locator(selectors.CELL_OUTPUT_IMAGE).evaluate_all(
                "els => els.map(e => e.src)"
            )
            images = self._save_image_srcs(cell_id, parent_imgs + iframe_imgs)

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

    def _read_iframe_outputs(self, cell) -> tuple[str, list[str], str]:
        """Drill into per-cell output iframes.

        Returns (error_text, [img_srcs], rich_text).

        The rich_text bucket catches DataFrame HTML tables, formatted reprs,
        and anything that ipykernel emits via `display_data` rather than
        `stream`. Selectors target Jupyter's standard output classes that
        Colab renders inside the outputframe iframe. Errors are extracted
        separately so cells with both an error and prior output don't double-
        count the traceback.
        """
        error_text = ""
        img_srcs: list[str] = []
        rich_text_parts: list[str] = []
        n = cell.locator("iframe").count()
        for i in range(n):
            frame = cell.frame_locator("iframe").nth(i)
            try:
                err = frame.locator(selectors.CELL_ERROR_IFRAME)
                err_count = err.count()
                if err_count:
                    error_text += "\n".join(err.all_inner_texts())

                imgs = frame.locator("img").evaluate_all("els => els.map(e => e.src)")
                img_srcs.extend(s for s in imgs if s)

                # Rich text — DataFrames, formatted reprs, HTML tables, repr output.
                # Skip when this iframe is the error iframe (already captured).
                if not err_count:
                    rich_nodes = frame.locator(selectors.CELL_OUTPUT_RICH)
                    if rich_nodes.count():
                        chunks = [t for t in rich_nodes.all_inner_texts() if t.strip()]
                        if chunks:
                            rich_text_parts.append("\n".join(chunks))
            except Exception:
                # Frame may be cross-origin or detached; skip.
                continue
        return error_text, img_srcs, "\n".join(rich_text_parts).strip()

    def _save_image_srcs(self, cell_id: str, srcs: list[str]) -> list[str]:
        """Decode base64 image srcs and write as PNG. Skips non-data URIs."""
        out_dir = _paths.RUNS_DIR / self.file_id / cell_id
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for i, src in enumerate(srcs):
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


def _merge_output_text(parent: str, rich: str) -> str:
    """Combine parent-stream text and iframe rich text, deduplicated.

    Cells often emit on only one surface — usually parent for stdout, iframe
    for DataFrame/object reprs. When both have content, we concatenate but
    skip the rich text if its content is a substring of the parent (Colab
    occasionally mirrors stream output into the iframe's rendering chrome).
    """
    parent = (parent or "").strip()
    rich = (rich or "").strip()
    if not parent:
        return rich
    if not rich or rich in parent:
        return parent
    return f"{parent}\n{rich}"


# ---------- Public entrypoints ----------


def run_one_cell(
    file_id: str, cell_id: str, runtime: str | None = None, timeout_sec: int = DEFAULT_RUN_TIMEOUT
) -> dict[str, Any]:
    with acquire_lock(), ColabSession(file_id, runtime=runtime) as sess:
        sess.connect_runtime(runtime)
        return sess.run_cell(cell_id, timeout_sec=timeout_sec).to_dict()


def run_all_cells(file_id: str, runtime: str | None = None) -> list[dict[str, Any]]:
    with acquire_lock(), ColabSession(file_id, runtime=runtime) as sess:
        sess.connect_runtime(runtime)
        return [r.to_dict() for r in sess.run_all()]


def run_all_native(
    file_id: str, runtime: str | None = None, timeout_sec: int = 3600
) -> dict[str, Any]:
    """Ephemeral wrapper around ColabSession.run_all_native — drives Colab's
    own Run All (Ctrl+F9) end-to-end, then closes the browser. Use when you
    need a single fire-and-forget run; use the persistent session daemon for
    iterative work where you want to inspect outputs between cells."""
    with acquire_lock(), ColabSession(file_id, runtime=runtime) as sess:
        sess.connect_runtime(runtime)
        return sess.run_all_native(timeout_sec=timeout_sec)


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
