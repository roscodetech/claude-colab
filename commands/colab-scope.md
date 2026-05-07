---
description: Show or change the Drive scope. Two independent dimensions: OAuth scope (what files Google lets us see) and folder filter (which folder we list from).
---

# /colab-scope

Two scopes, distinct, settable independently:

- **OAuth scope** — controls what Google lets the plugin read/write. `file` = only files we created or that were explicitly opened with this app (default, narrowest). `full` = read+write access to every file in the user's Drive (required to discover and edit pre-existing notebooks like ones created via the Colab UI).
- **Folder filter** — purely a query convenience. When narrow, `/colab-list` only shows notebooks inside the configured folder (default `claude-colab`). When `--full`, lists across all folders the OAuth scope allows.

## Action

Show current scopes:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope --human
```

Widen OAuth so agents can see existing notebooks:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope --oauth full
# Then re-auth:
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" auth
```

Narrow OAuth back to default:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope --oauth file
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" auth
```

Change folder filter:
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope --folder "my-notebooks"
```

Lift folder filter (list across all folders):
```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" scope --full
```

## Important

When `--oauth` changes:
- The persisted Drive token is deleted (Google won't extend an existing token to a wider scope).
- The next Drive call requires re-auth — surface this to the user via `/colab-auth`.

## When to suggest `--oauth full`

- User explicitly wants to work with notebooks created outside the plugin.
- User says "fix my existing notebook" and a `/colab-list` returns empty.

Never widen automatically. The narrow scope is a real safety property; only loosen it on explicit user request.
