---
description: Re-fetch saved output text for a cell (no re-execution)
---

# /colab-output

Reads the persisted notebook from Drive and returns the text outputs of a cell. Useful when the user wants to inspect a previous run's result without re-running.

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" output "$FILE_ID" "$CELL_ID"
```

## Notes

- Returns concatenated text from stream / execute_result / error outputs.
- Does **not** return images. For images, look in `~/.claude-colab/runs/<file_id>/<cell_id>/`.
- This reads what was last saved to Drive, which means if Colab autosave hadn't completed before the previous read, output may be stale by a few seconds.
