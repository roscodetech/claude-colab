"""One-off DOM probe — open a tiny canary, RUN cells, dump output-area structure.

Helps figure out the post-run DOM (output containers, error styling, image
placement) when Colab ships UI changes. Re-run after any selector drift the
selftest reports.

Run: ~/.claude-colab/.venv/Scripts/python -m scripts.probe
"""

from __future__ import annotations

import json
import time

from playwright.sync_api import sync_playwright

from . import drive, notebook
from . import paths as _paths
from . import selectors as sel


def main() -> None:
    nb_meta = drive.create_notebook("claude-colab-probe")
    file_id = nb_meta["id"]
    try:
        nb, rev = notebook.read(file_id)
        nb.cells = []
        notebook.add_cell(nb, "print('probe stdout')", cell_type="code")
        notebook.add_cell(
            nb,
            "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
            "plt.plot([1,2,3]); plt.savefig('p.png'); plt.show()",
            cell_type="code",
        )
        notebook.add_cell(nb, "raise ValueError('probe error')", cell_type="code")
        notebook.write(file_id, nb, expected_revision=rev)

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

            # Click connect (best effort)
            import contextlib

            with contextlib.suppress(Exception):
                page.locator(sel.CONNECT_BUTTON).first.click(timeout=5_000)
            time.sleep(3)

            # Click run on each cell
            cells = page.query_selector_all(sel.CELL_LIST)
            print(f"found {len(cells)} cells", flush=True)
            for i, cell in enumerate(cells):
                cell.scroll_into_view_if_needed()
                cell.hover()
                run_btn = cell.query_selector(sel.CELL_RUN_BUTTON)
                if run_btn:
                    run_btn.click()
                    print(f"clicked run on cell {i}", flush=True)
                time.sleep(15)  # let it run

            # Wait an extra beat for outputs to render fully
            time.sleep(5)

            # First — count iframes and show their src/structure
            iframe_report = page.evaluate("""
                () => {
                    const cells = [...document.querySelectorAll('div.cell.notebook-cell')];
                    return cells.map((cell, idx) => {
                        const iframes = [...cell.querySelectorAll('iframe')];
                        return {
                            idx,
                            cell_id: cell.getAttribute('id'),
                            n_iframes: iframes.length,
                            iframes: iframes.map(f => ({
                                src: (f.src || '').slice(0, 80),
                                name: f.name || '',
                                id: f.id || '',
                                cls: typeof f.className === 'string' ? f.className : '',
                            })),
                        };
                    });
                }
            """)
            print("=== iframe structure ===", flush=True)
            print(json.dumps(iframe_report, indent=2), flush=True)

            # Try to peer inside each iframe via Playwright's frame API.
            print("\n=== iframe contents (via Playwright frames) ===", flush=True)
            for idx, frame in enumerate(page.frames):
                try:
                    body_html = frame.evaluate(
                        """() => {
                            const imgs = [...document.querySelectorAll('img')].length;
                            const errors = [...document.querySelectorAll('*')].filter(e => {
                                const c = (typeof e.className === 'string' ? e.className : '');
                                return /error|stderr|traceback|exception/i.test(c);
                            }).map(e => ({
                                tag: e.tagName.toLowerCase(),
                                cls: (typeof e.className === 'string' ? e.className : '').slice(0, 80),
                                text_head: (e.innerText || '').slice(0, 100).replace(/\\n/g, '\\\\n'),
                            }));
                            const txt = (document.body && document.body.innerText || '').slice(0, 200);
                            return { url: location.href.slice(0, 80), imgs, errors, txt };
                        }"""
                    )
                    print(f"frame {idx}:", json.dumps(body_html, indent=2), flush=True)
                except Exception as e:
                    print(f"frame {idx}: ERR {e}", flush=True)

            # Original report
            report = page.evaluate("""
                () => {
                    const cells = [...document.querySelectorAll('div.cell.notebook-cell')];
                    return cells.map((cell, idx) => {
                        // Find output-ish descendants
                        const outputs = [];
                        cell.querySelectorAll('*').forEach(el => {
                            const tag = el.tagName.toLowerCase();
                            const cls = (typeof el.className === 'string') ? el.className : '';
                            const interesting = (
                                /output|stream|error|stderr|stdout|result|exec/i.test(cls) ||
                                /output|stream|error|result/i.test(tag)
                            );
                            if (interesting) {
                                outputs.push({
                                    tag,
                                    cls: cls.slice(0, 100),
                                    has_img: !!el.querySelector('img'),
                                    text_len: (el.innerText || '').length,
                                    text_head: (el.innerText || '').slice(0, 60).replace(/\\n/g, '\\\\n'),
                                });
                            }
                        });
                        // Also look for img elements anywhere in the cell
                        const imgs = [...cell.querySelectorAll('img')].map(i => ({
                            src_kind: i.src ? i.src.slice(0, 30) : '',
                            parent_cls: (typeof i.parentElement?.className === 'string'
                                ? i.parentElement.className : '').slice(0, 60),
                        }));
                        // Dedupe by sig
                        const seen = new Set();
                        const dedup = outputs.filter(o => {
                            const k = o.tag + '|' + o.cls;
                            if (seen.has(k)) return false;
                            seen.add(k); return true;
                        });
                        return {
                            idx,
                            cell_id: cell.getAttribute('id'),
                            n_imgs: imgs.length,
                            imgs,
                            n_outputs: outputs.length,
                            unique_output_shapes: dedup.slice(0, 12),
                        };
                    });
                }
            """)
            print(json.dumps(report, indent=2))
            ctx.close()
    finally:
        drive.delete_notebook(file_id, hard=True)


if __name__ == "__main__":
    main()
