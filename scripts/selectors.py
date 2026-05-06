"""Colab DOM selectors — centralized so we have one place to fix when Google ships UI changes.

If something breaks, run /colab-selftest. It runs each selector against a
canary notebook and prints a per-selector report.

Versioning: bump SCHEMA_VERSION when selectors meaningfully change so users
running stale plugins get a clear hint.
"""

SCHEMA_VERSION = "2026-05-06"

# Top-level chrome
CONNECT_BUTTON = 'colab-connect-button, [aria-label*="Connect"]'
RUNTIME_MENU = '[aria-label="Runtime"]'
RUNTIME_CHANGE = 'text="Change runtime type"'
RUNTIME_HARDWARE_SELECT = 'mwc-select[aria-label*="Hardware accelerator"]'
RUNTIME_SAVE = 'paper-button[dialog-confirm], button:has-text("Save")'

# Cells — Colab wraps each cell in a `<div class="cell ...">` with a stable
# `data-cell-id` attribute that maps to the nbformat id (Colab adds it on load).
CELL_BY_ID = 'div.cell[data-cell-id="{cell_id}"]'
CELL_RUN_BUTTON = 'colab-run-button, [aria-label*="Run cell"]'
CELL_OUTPUT_AREA = ".output-area, .output_area"
CELL_OUTPUT_TEXT = ".output-area .output-content, .output-content"
CELL_OUTPUT_IMAGE = ".output-area img, .output_area img"
CELL_ERROR = ".output-area .error-output, .output_subarea.output_error"
CELL_BUSY = ".cell.running, .cell[busy]"

# "Run all" lives under the Runtime menu
RUN_ALL_MENU_ITEM = 'text="Run all"'

# Sign-in detection — used by browser login flow
SIGNED_IN_PROBE = 'a[aria-label*="Google Account"]'

# Save indicator (Colab autosaves; we wait for "Saved" before closing)
SAVE_STATUS_SAVED = "text=/All changes saved/i"
