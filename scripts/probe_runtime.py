"""Probe the Runtime menu + change-runtime-type dialog DOM.

Opens a notebook, dumps anything that looks like the Runtime menu button or
related UI. Used to keep RUNTIME_MENU / RUNTIME_CHANGE / RUNTIME_HARDWARE_SELECT
/ RUNTIME_SAVE selectors current.

Run: ~/.claude-colab/.venv/Scripts/python -m scripts.probe_runtime
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
    nb_meta = drive.create_notebook("claude-colab-rt-probe")
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
            time.sleep(3)  # let menubar render

            # Dump everything matching "runtime" anywhere
            menu_candidates = page.evaluate("""
                () => {
                    const out = [];
                    document.querySelectorAll('*').forEach(el => {
                        const text = (el.innerText || '').trim();
                        const aria = el.getAttribute('aria-label') || '';
                        const cls = (typeof el.className === 'string' ? el.className : '');
                        const tag = el.tagName.toLowerCase();
                        // Only top-of-page elements (skip cell-internal)
                        const r = el.getBoundingClientRect();
                        if (r.top > 200) return;
                        if (
                            /runtime/i.test(aria) ||
                            (text === 'Runtime' || text.startsWith('Runtime')) ||
                            /runtime/i.test(cls)
                        ) {
                            out.push({
                                tag,
                                aria: aria.slice(0, 60),
                                text: text.slice(0, 50).replace(/\\n/g, ' '),
                                cls: cls.slice(0, 80),
                                top: Math.round(r.top),
                            });
                        }
                    });
                    // Dedupe by signature
                    const seen = new Set();
                    return out.filter(o => {
                        const k = `${o.tag}|${o.aria}|${o.text.slice(0,20)}`;
                        if (seen.has(k)) return false;
                        seen.add(k);
                        return true;
                    });
                }
            """)
            print("=== runtime menu candidates ===", flush=True)
            print(json.dumps(menu_candidates, indent=2), flush=True)

            # Now try to click whatever looks most like the menu — pick the
            # first candidate that's a button/menu-button/link with text "Runtime"
            best = None
            for c in menu_candidates:
                if c["text"].strip() == "Runtime" and c["tag"] in (
                    "div",
                    "button",
                    "span",
                    "a",
                    "colab-menu-button",
                ):
                    best = c
                    break
            print(f"\n=== best guess for runtime menu: {best} ===", flush=True)

            if best:
                # Click it and dump what appears in the dropdown
                try:
                    locator = page.locator(f"{best['tag']}:has-text('Runtime')").first
                    locator.click(timeout=5_000)
                    time.sleep(1.5)

                    menu_items = page.evaluate("""
                        () => {
                            const out = [];
                            document.querySelectorAll('mwc-list-item, [role="menuitem"], .mat-menu-item, paper-item').forEach(el => {
                                const text = (el.innerText || '').trim();
                                if (!text) return;
                                out.push({
                                    tag: el.tagName.toLowerCase(),
                                    text: text.slice(0, 80).replace(/\\n/g, ' '),
                                    aria: el.getAttribute('aria-label') || '',
                                });
                            });
                            return out.slice(0, 30);
                        }
                    """)
                    print("\n=== open menu items ===", flush=True)
                    print(json.dumps(menu_items, indent=2), flush=True)
                except Exception as e:
                    print(f"click failed: {e}", flush=True)

            ctx.close()
    finally:
        with contextlib.suppress(Exception):
            drive.delete_notebook(file_id, hard=True)


if __name__ == "__main__":
    main()
