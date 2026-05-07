---
description: Spawn a persistent session daemon — long-lived browser + warm Colab runtime so successive /colab-run calls share kernel state. Use before any iterative cell-running workflow.
---

# /colab-open

Opens a persistent session for one notebook. The daemon runs in the background, holds the file lock for its lifetime, and serves cell-run commands over a localhost socket. Subsequent `/colab-run` calls against the same notebook reuse this session — kernel state (imports, loaded data, trained models) is preserved across runs.

## When to use

- Iterative debugging on a single cell (run → see error → edit → re-run)
- Notebook authoring with the planner→executor→debugger flow
- Anything that runs more than one cell in sequence and expects shared state

## When NOT to use

- One-off cell run with no follow-up — `/colab-run` ephemeral mode is faster (no need to spin up a daemon for a single shot)
- Just looking at a notebook — open `webViewLink` from `/colab-list` directly

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" open "$FILE_ID"
```

Optional flags:
- `--runtime cpu|gpu|tpu` — overrides the default
- `--timeout N` — seconds to wait for daemon to be ready (default 120)

## After running

Successful response includes the session pid + port. Tell the user it's ready and follow up with their actual task. **Always close the session** when done with `/colab-close` — leaving it open holds the lock and consumes a Colab runtime slot.

## Failure modes

- `another session is already active for X` — `/colab-status` to inspect, `/colab-close` to free it
- `session daemon failed to start within timeout` — check `~/.claude-colab/session.log`
