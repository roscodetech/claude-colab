---
description: Open a notebook in headed Chromium for inspection (does not lock — safe to use alongside other commands)
---

# /colab-open

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" open "$FILE_ID"
```

Where `$FILE_ID` is the Drive file id (from `/colab-list`).

## Notes

- Doesn't acquire the run-lock — opening is read-only from our side; the user is just looking.
- Closes nothing — the window stays open until the user closes it.
