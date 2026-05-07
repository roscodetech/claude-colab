"""Open the Runtime > Change runtime type dialog and dump its contents."""

from __future__ import annotations

import contextlib
import json
import time

from playwright.sync_api import sync_playwright

from . import drive
from . import paths as _paths
from . import selectors as sel


def main() -> None:
    nb_meta = drive.create_notebook("claude-colab-rt-dialog-probe")
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

            # Open the Runtime menu
            page.locator(".goog-menu-button").filter(has_text="Runtime").first.click()
            time.sleep(0.5)
            page.click('text="Change runtime type"')
            time.sleep(2)  # let dialog render

            # Dump every input-like element in the dialog
            dialog_dom = page.evaluate("""
                () => {
                    const out = [];
                    document.querySelectorAll(
                        'mwc-select, md-outlined-select, select, mwc-radio, '
                        + 'md-radio, [role="radio"], [role="radiogroup"], '
                        + 'md-list-item, mwc-list-item, paper-radio-button, '
                        + 'mat-radio-button, md-filled-select, md-outlined-button, '
                        + 'paper-button, button, md-text-button'
                    ).forEach(el => {
                        const tag = el.tagName.toLowerCase();
                        const text = (el.innerText || '').trim().slice(0, 60);
                        const aria = el.getAttribute('aria-label') || '';
                        const cls = (typeof el.className === 'string' ? el.className : '');
                        out.push({
                            tag,
                            text: text.replace(/\\n/g, ' '),
                            aria: aria.slice(0, 80),
                            cls: cls.slice(0, 80),
                        });
                    });
                    const seen = new Set();
                    return out.filter(o => {
                        const k = `${o.tag}|${o.text}|${o.aria}`;
                        if (seen.has(k)) return false;
                        seen.add(k);
                        return true;
                    });
                }
            """)
            print("=== dialog input candidates ===", flush=True)
            print(json.dumps(dialog_dom, indent=2), flush=True)

            ctx.close()
    finally:
        with contextlib.suppress(Exception):
            drive.delete_notebook(file_id, hard=True)


if __name__ == "__main__":
    main()
