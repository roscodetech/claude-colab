---
description: List Colab notebooks in the current Drive scope (default: claude-colab/ folder)
---

# /colab-list

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" list
```

Optionally pass `--limit N` (default 50).

## Format the output

Show a compact table: `name | id (last 8 chars) | modifiedTime` so user can pick one to open or run.

If the list is empty, suggest `/colab-new <name>` to create one, or `/colab-scope --full` to widen scope if they expect existing notebooks elsewhere.
