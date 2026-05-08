"""Probe what Playwright's CSS locator can actually see inside the
colab-runtime-attributes-selector shadow DOM. Tests several candidate
strategies and reports which find the radios.
"""

from __future__ import annotations

import contextlib
import json
import time

from playwright.sync_api import sync_playwright

from . import drive
from . import paths as _paths
from . import selectors as sel


def main() -> None:
    nb_meta = drive.create_notebook("claude-colab-rt-dialog-probe3")
    file_id = nb_meta["id"]
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(_paths.BROWSER_PROFILE_DIR),
                headless=False,
                channel="chromium",
                viewport={"width": 1400, "height": 900},
            )
            page = ctx.new_page()
            page.goto(
                f"https://colab.research.google.com/drive/{file_id}",
                wait_until="domcontentloaded",
            )
            page.wait_for_selector(sel.CELL_LIST, timeout=30_000)
            time.sleep(2)
            page.locator(".goog-menu-button").filter(has_text="Runtime").first.click()
            time.sleep(0.5)
            page.click('text="Change runtime type"')
            time.sleep(2.5)

            # 1. Light-DOM-only count of mwc-radio
            try_selectors = [
                "mwc-radio",
                'mwc-radio[aria-label="A100 GPU"]',
                'mwc-radio[aria-label*="GPU"]',
                'colab-runtime-attributes-selector mwc-radio',
                'colab-runtime-attributes-selector >> mwc-radio',
            ]
            results = {}
            for s in try_selectors:
                try:
                    results[s] = page.locator(s).count()
                except Exception as e:
                    results[s] = f"ERR: {e}"

            # 2. get_by_label (shadow-piercing by design)
            for label in ("A100 GPU", "T4 GPU", "GPU", "CPU"):
                try:
                    results[f"get_by_label({label!r})"] = page.get_by_label(label).count()
                except Exception as e:
                    results[f"get_by_label({label!r})"] = f"ERR: {e}"

            # 3. JS walk: find all mwc-radio across all open shadow roots
            js_count = page.evaluate("""
                () => {
                    function walk(root, out) {
                        if (root.tagName && root.tagName.toLowerCase() === 'mwc-radio') {
                            out.push({
                                aria: root.getAttribute('aria-label') || '',
                                checked: root.hasAttribute('checked'),
                                disabled: root.hasAttribute('disabled'),
                            });
                        }
                        if (root.shadowRoot) {
                            for (const c of root.shadowRoot.querySelectorAll('*')) walk(c, out);
                        }
                        for (const c of root.children || []) walk(c, out);
                    }
                    const out = [];
                    walk(document.documentElement, out);
                    return out;
                }
            """)

            print("=== Playwright locator counts ===")
            for k, v in results.items():
                print(f"  {k!r}: {v}")
            print()
            print("=== JS walk found mwc-radio elements ===")
            print(json.dumps(js_count, indent=2))

            ctx.close()
    finally:
        with contextlib.suppress(Exception):
            drive.delete_notebook(file_id, hard=True)


if __name__ == "__main__":
    main()
