---
description: Show whether a persistent session is active, for which notebook, and how long it's been up.
---

# /colab-status

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" status --human
```

## Output

- `active: false` → no session. /colab-run uses ephemeral mode.
- `active: true, responsive: true` → session is up and reachable. /colab-run will reuse it for the listed `file_id`.
- `active: true, responsive: false` → session.json says alive but daemon isn't answering pings. Likely zombie; recommend `/colab-close` to clean up.

Includes `uptime_sec` so users can spot stale sessions.
