---
description: One-time Drive OAuth — opens browser, user signs in, refresh token persisted to ~/.claude-colab/drive_token.json
---

# /colab-auth

Authorize Drive API access. Required before any Drive CRUD.

## Prerequisites

User must have placed an OAuth client JSON at `~/.claude-colab/drive_credentials.json`.

If that file is missing, instruct them once:

1. Visit https://console.cloud.google.com/
2. Create or pick a project, enable the Google Drive API
3. APIs & Services → Credentials → Create OAuth client ID → Desktop app
4. Download JSON, save to `~/.claude-colab/drive_credentials.json`

(Takes ~2 minutes. We don't ship a shared client because Drive scope sharing across users gets rate-limited and Google can suspend a client used at scale.)

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" auth
```

If user passed `--force` or said "re-auth", add `--force` to the command. This wipes the token and re-runs the consent flow.

## After running

- Success: confirm with one line (`Drive auth ok`).
- "Missing OAuth client" error: surface the setup instructions above.
