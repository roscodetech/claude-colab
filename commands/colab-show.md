---
description: Print a compact summary of cells in a notebook (id, type, first lines) — use before editing or running
---

# /colab-show

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" show "$FILE_ID"
```

## Format

For each cell, show:
- `[idx] cell_id (type)` first 2 lines of source
- `*` marker if the cell has prior outputs

This is the cheapest way to give the planner / executor agents context about an existing notebook before they edit it.
