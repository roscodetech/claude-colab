---
description: Cleanly shut down the active session daemon. Releases the file lock and frees the Colab runtime.
---

# /colab-close

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" close
```

## Behavior

- If a session is active → sends `quit` over the IPC socket. Daemon closes the browser, deletes session.json, releases the lock, exits.
- If session.json is stale (daemon crashed) → cleans up the file and reports.
- If no session is active → no-op, returns `note: no active session`.

## When to suggest this

After any `/colab-open`-driven workflow when the user is done. If the user asks about runtime quotas, network errors, or "I can't open another session", check status and recommend closing.
