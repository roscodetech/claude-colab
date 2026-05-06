---
description: Delete a notebook (trash by default; pass --hard for permanent)
---

# /colab-delete

## Action

Trash:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" delete "$FILE_ID"
```

Permanent (irreversible):
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" delete "$FILE_ID" --hard
```

## Confirmation

Always confirm with the user before running `--hard`. Trash is recoverable from drive.google.com/drive/trash; permanent delete is not.
