---
description: Execute one cell or all cells. Uses the active session if /colab-open was called for this notebook (fast, kernel state preserved); otherwise runs ephemerally (slow, kernel state lost between runs).
---

# /colab-run

## Two modes

**Session mode** (preferred for iterative work):
- Requires `/colab-open <FILE_ID>` first
- Subsequent runs reuse the same browser + Colab runtime
- Kernel state preserved (imports, loaded models, mounted Drive)
- ~3s round-trip per cell after warmup

**Ephemeral mode** (auto-fallback when no session is active):
- New browser + new runtime per call (~30-60s overhead)
- Kernel state lost between calls
- Fine for one-shot runs

The CLI picks automatically based on the active session. The response includes a `via` field (`"session"` or `"ephemeral"`) so the agent can see which path was taken.

## Action

Single cell:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" run "$FILE_ID" --cell "$CELL_ID"
```

All cells:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" run "$FILE_ID" --all
```

Optional:
- `--runtime cpu|gpu|tpu` — only honored in ephemeral mode (session locks runtime at /colab-open time)
- `--timeout N` — per-cell timeout in seconds (default 600)

## Result format

```json
{
  "status": "ok",
  "via": "session" | "ephemeral",
  "result": {
    "cell_id": "...",
    "status": "ok | error | timeout",
    "stdout": "...",
    "error_text": "...",
    "images": ["/path/to/img.png"],
    "duration_ms": 1234
  }
}
```

## Cross-notebook safety

If a session is active for a DIFFERENT notebook than the one you're running against, the call fails loud — running ephemerally would block on the lock anyway. `/colab-close` first or use the active notebook.

## When to suggest /colab-open

If the user is going to run more than one cell, or wants to iterate on a single cell with edits, recommend `/colab-open` *before* the first run. Otherwise each ephemeral run loses the runtime.
