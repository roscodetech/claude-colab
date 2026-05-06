---
description: Execute one cell or all cells in a notebook via headed Chromium. Captures stdout, errors, and plot images.
---

# /colab-run

Drives the notebook in Chromium, clicks Run, captures output. **Locks** — only one notebook can be running at a time.

## Action

Single cell:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" run "$FILE_ID" --cell "$CELL_ID"
```

All cells:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" run "$FILE_ID" --all
```

Optional flags:
- `--runtime cpu|gpu|tpu` — overrides default
- `--timeout N` — per-cell timeout in seconds (default 600)

## Result format

Per-cell:
```json
{"cell_id": "...", "status": "ok|error|timeout", "stdout": "...", "error_text": "...", "images": ["/path/to/img.png"], "duration_ms": 1234}
```

## After running

- All `ok`: summarize stdout briefly.
- Any `error`: read `error_text`. If user asked for autonomous fixing, spawn the **colab-debugger** subagent with the failing cell + error + last N cell stdouts. After debugger returns a proposed fix, apply via `/colab-edit` and re-run that cell. Cap retries at the user's `debugger_max_retries` config (default 2).
- `timeout`: warn the user; do not auto-retry (likely an infinite loop or stuck runtime).

## Lock behavior

If output shows `ColabBusyError`, another session has the lock. Tell user to wait or check `~/.claude-colab/colab.lock` if they're sure nothing's running.
