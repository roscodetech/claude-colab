---
description: One-time Colab browser login — launches headed Chromium with a dedicated profile, user signs in once, cookies persisted
---

# /colab-login

Sign the user into Colab in the dedicated `~/.claude-colab/chrome-profile/` so the browser layer can drive notebooks without re-prompting.

This is independent from `/colab-auth` (Drive OAuth). Both are needed for full functionality.

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" login
```

This opens a Chromium window pointed at colab.research.google.com. The user signs in (same Google account they want notebooks under). The script polls for an authed cookie and exits when detected, or after 5 min timeout.

## After running

- `status: ok` → confirm and suggest `/colab-list` as the next step.
- `status: timeout` → user didn't finish signing in; suggest re-running.
