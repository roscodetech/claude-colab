"""Colab DOM selectors — centralized so we have one place to fix when Google ships UI changes.

If something breaks, run /colab-selftest. It runs each selector against a
canary notebook and prints a per-selector report.

Versioning: bump SCHEMA_VERSION when selectors meaningfully change so users
running stale plugins get a clear hint.
"""

SCHEMA_VERSION = "2026-05-07c"

# Top-level chrome
CONNECT_BUTTON = 'colab-connect-button, [aria-label*="Connect"]'
# Runtime menu is a Closure goog-menu-button. The label is wrapped in
# whitespace/nested spans, so :text-is misses; browser.connect_runtime uses
# locator(".goog-menu-button").filter(has_text="Runtime") instead. Kept here
# as documentation of the parent class.
RUNTIME_MENU_CLASS = ".goog-menu-button"
RUNTIME_CHANGE = 'text="Change runtime type"'
# WARNING — runtime-type dialog selectors have shifted to Material 3
# (md-* components) and we haven't pinned the exact hardware-picker selector
# yet. Probed empirically 2026-05-07: dialog contains md-text-button (Save,
# Cancel) but the hardware accelerator chooser uses a different element type
# we haven't isolated. Run scripts/probe_runtime_dialog.py to enumerate
# candidates if you're fixing this. Until then, --runtime gpu/tpu open paths
# fail at this dialog and fall back to whatever runtime Colab assigns by
# default (usually CPU).
RUNTIME_HARDWARE_SELECT = 'mwc-select[aria-label*="Hardware accelerator"]'
RUNTIME_SAVE = 'paper-button[dialog-confirm], button:has-text("Save")'

# Cells — Colab wraps each cell in a `<div class="cell code notebook-cell">`
# with `id="cell-<nbformat-id>"` (stable nbformat 4.5 ids preserved on load).
# Probed empirically 2026-05-07; previous schema used data-cell-id which is gone.
CELL_LIST = "div.cell.notebook-cell"  # all cells in DOM order
CELL_BY_ID = 'div.cell[id="cell-{cell_id}"]'
CELL_RUN_BUTTON = 'colab-run-button, [aria-label*="Run cell"]'
CELL_OUTPUT_AREA = ".output-area, .output_area"
CELL_OUTPUT_TEXT = ".output-area .output-content, .output-content"
CELL_OUTPUT_IMAGE = ".output-area img, .output_area img"
CELL_ERROR = ".output-area .error-output, .output_subarea.output_error"
# Inside Colab's per-cell output iframe, errors render as `.error.output-error`.
# Images live in <img> tags. Selectors apply to the iframe's document.
CELL_ERROR_IFRAME = ".error, .output-error, .traceback"
# Rich-text containers inside the iframe — DataFrame tables, formatted reprs,
# HTML output, execute_result output. Order matters: more-specific first so
# the inner text doesn't get double-counted by a wrapping ancestor.
CELL_OUTPUT_RICH = (
    ".output_html, .output_text, .output-content, .stream, .rendered_html, table.dataframe, pre"
)
CELL_BUSY = ".cell.running, .cell[busy]"

# "Run all" lives under the Runtime menu
RUN_ALL_MENU_ITEM = 'text="Run all"'

# Sign-in detection — used by browser login flow
SIGNED_IN_PROBE = 'a[aria-label*="Google Account"]'

# Save indicator (Colab autosaves; we wait for "Saved" before closing)
SAVE_STATUS_SAVED = "text=/All changes saved/i"
