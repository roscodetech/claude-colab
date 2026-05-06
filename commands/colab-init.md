---
description: First-run wizard — sets Drive scope, image saving, default runtime, debugger retry budget. Idempotent.
---

# /colab-init

Run the bundled installer + wizard. Use this once on a fresh machine, or any time the user wants to change defaults.

## Action

Execute via the launcher:

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" init
```

Pass any of these flags through if the user specified them:

- `--scope-folder NAME` — restrict Drive scope to a single folder (default: `claude-colab`)
- `--scope-full` — extend scope to the whole Drive (warn user before doing this)
- `--images` / `--no-images` — save plot/output images to disk
- `--retries N` — debugger auto-retry budget (default 2)
- `--runtime cpu|gpu|tpu` — default runtime
- `--reset` — restore all defaults

## After running

- If output shows a missing OAuth client, point user to `/colab-auth` and the README's "Drive credentials" section.
- Otherwise summarize the resulting config in plain English (one bullet per non-default setting).
