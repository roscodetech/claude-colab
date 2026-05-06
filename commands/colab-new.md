---
description: Create a new Colab notebook in the current scope folder
---

# /colab-new

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" new "$NAME"
```

Where `$NAME` is the user-supplied notebook name. `.ipynb` extension added automatically if missing.

## After running

Return the new notebook's `id` and `webViewLink`. Suggest `/colab-edit` to add cells, or `/colab-open` to view it in browser.
