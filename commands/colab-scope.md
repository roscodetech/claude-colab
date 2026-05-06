---
description: Show or change the Drive scope (default: claude-colab/ folder only)
---

# /colab-scope

## Action

Show current scope:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope
```

Change folder:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope --folder "my-notebooks"
```

Widen to full Drive (warn user — agents will then see every notebook in their Drive):
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope --full
```

## When to suggest widening

Only suggest `--full` if the user explicitly asks to work with notebooks outside the scope folder. Default-narrow is a safety property; don't erode it casually.
