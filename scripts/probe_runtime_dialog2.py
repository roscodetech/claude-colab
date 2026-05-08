"""Wider-net probe of the runtime dialog. Dumps every element type inside
the dialog with text/aria-label, plus the dialog's full innerHTML truncated."""

from __future__ import annotations

import contextlib
import json
import time

from playwright.sync_api import sync_playwright

from . import drive
from . import paths as _paths
from . import selectors as sel


def main() -> None:
    nb_meta = drive.create_notebook("claude-colab-rt-dialog-probe2")
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
            time.sleep(2)

            # Find any open dialog and dump every descendant
            data = page.evaluate("""
                () => {
                  // Find the visible dialog
                  const dialogs = Array.from(document.querySelectorAll(
                    'mwc-dialog[open], dialog[open], md-dialog[open], '
                    + '[role="dialog"], paper-dialog'
                  )).filter(d => d.offsetParent !== null || d.getBoundingClientRect().width > 0);
                  if (!dialogs.length) {
                    return {error: "no open dialog found", count: 0};
                  }
                  const d = dialogs[0];
                  const all = d.querySelectorAll('*');
                  const tagCounts = {};
                  const interesting = [];
                  for (const el of all) {
                    const tag = el.tagName.toLowerCase();
                    tagCounts[tag] = (tagCounts[tag] || 0) + 1;
                    // Capture anything that looks input-y or has text
                    const text = (el.innerText || '').trim().slice(0, 50);
                    const aria = el.getAttribute('aria-label') || '';
                    const role = el.getAttribute('role') || '';
                    const id = el.id || '';
                    const cls = (typeof el.className === 'string' ? el.className : '').slice(0, 50);
                    if (
                      tag.includes('select') || tag.includes('radio') ||
                      tag.includes('checkbox') || tag.includes('option') ||
                      tag.includes('list') || tag.includes('button') ||
                      role === 'radio' || role === 'option' || role === 'button' ||
                      role === 'combobox'
                    ) {
                      interesting.push({tag, text: text.replace(/\\n/g, ' '), aria, role, id, cls});
                    }
                  }
                  // Also dump the dialog's full HTML (truncated) to spot
                  // structure that the per-element view might miss.
                  const html = d.outerHTML.slice(0, 6000);
                  // Walk into open shadow roots — the runtime selector is a
                  // Lit web component whose internals live in a shadow DOM.
                  function deepDescendants(root, depth = 0, max = 6) {
                    if (depth > max) return [];
                    const out = [];
                    const queue = [{node: root, depth}];
                    while (queue.length) {
                      const {node, depth: dep} = queue.shift();
                      if (node.shadowRoot) {
                        for (const ch of node.shadowRoot.querySelectorAll('*')) {
                          out.push({
                            tag: ch.tagName.toLowerCase(),
                            text: (ch.innerText || ch.textContent || '').trim().slice(0, 40).replace(/\\n/g,' '),
                            aria: ch.getAttribute('aria-label') || '',
                            role: ch.getAttribute('role') || '',
                            id: ch.id || '',
                            cls: (typeof ch.className === 'string' ? ch.className : '').slice(0, 40),
                            depth: dep + 1,
                          });
                          queue.push({node: ch, depth: dep + 1});
                        }
                      }
                      for (const ch of node.children || []) {
                        queue.push({node: ch, depth: dep + 1});
                      }
                    }
                    return out;
                  }
                  const selector = d.querySelector('colab-runtime-attributes-selector');
                  const shadow = selector ? deepDescendants(selector) : [];
                  return {tagCounts, interesting, html, dialog_tag: d.tagName.toLowerCase(),
                          dialog_id: d.id, dialog_cls: d.className,
                          selector_descendants: shadow};
                }
            """)
            print("=== probe2 ===")
            print(json.dumps(data, indent=2))

            ctx.close()
    finally:
        with contextlib.suppress(Exception):
            drive.delete_notebook(file_id, hard=True)


if __name__ == "__main__":
    main()
