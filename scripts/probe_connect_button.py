"""Dump the aria-label / inner text of Colab's connect button in both
disconnected and connected states. Used to validate
ColabSession.attached_runtime_kind()."""

from __future__ import annotations

import json
import time

from playwright.sync_api import sync_playwright

from . import paths as _paths
from . import selectors as sel

FILE_ID = "1KS9Auu-NSjQZjOSBwrVrQ9_00lBPrP-G"


def main() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(_paths.BROWSER_PROFILE_DIR),
            headless=False,
            channel="chromium",
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()
        page.goto(
            f"https://colab.research.google.com/drive/{FILE_ID}",
            wait_until="domcontentloaded",
        )
        page.wait_for_selector(sel.CELL_LIST, timeout=30_000)
        time.sleep(3)

        # Probe everything that looks like a connection-state element.
        snap = page.evaluate("""
            () => {
              const out = [];
              const sels = [
                'colab-connect-button',
                '[aria-label*="Connect"]',
                '[aria-label*="onnected"]',
                'colab-toolbar-button[command*="connect"]',
                'colab-resource-display',
                '.connect-button',
              ];
              for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                  out.push({
                    selector: s,
                    tag: el.tagName.toLowerCase(),
                    aria: el.getAttribute('aria-label') || '',
                    title: el.getAttribute('title') || '',
                    text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
                    cls: (typeof el.className === 'string' ? el.className : '').slice(0, 60),
                  });
                }
              }
              return out;
            }
        """)
        print("=== connect-button probe ===")
        print(json.dumps(snap, indent=2))

        ctx.close()


if __name__ == "__main__":
    main()
