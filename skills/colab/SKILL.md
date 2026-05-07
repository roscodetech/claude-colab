---
name: colab
description: Drive Google Colab notebooks from Claude Code. CRUD via Drive API, execute cells via headed Chromium, capture text and image output. Use when the user wants to create, edit, run, or inspect Colab notebooks, or build a notebook from a goal description.
---

# colab — Google Colab from Claude Code

When to invoke: user says "Colab", "notebook", "ipynb", "Drive notebook", or asks to load a dataset and train a model in a hosted runtime.

When **not** to invoke: local Jupyter (no Drive component), pure scripting tasks (use Bash directly), or notebooks already open in their IDE (just edit the file).

## Capability map

| User intent | Tool |
|---|---|
| First-time setup | `/colab-init`, `/colab-auth`, `/colab-login` |
| List my notebooks | `/colab-list` |
| Make a new one | `/colab-new <name>` |
| Look inside one (cell list) | `/colab-show <id>` |
| Add / edit / delete a cell | `/colab-edit <id> <action>` |
| **Open a persistent session** (warm runtime) | `/colab-open <id>` |
| Run a cell or all cells | `/colab-run <id> --cell <cid>` or `--all` |
| Get last output text | `/colab-output <id> <cell>` |
| Check / close session | `/colab-status`, `/colab-close` |
| Trash / permanently delete | `/colab-delete <id>` |
| Change Drive scope (OAuth + folder) | `/colab-scope` |
| Diagnose UI breakage | `/colab-selftest` |
| **"Build me a notebook that does X"** | spawn `colab-planner` → review with user → spawn `colab-executor` (which opens its own session) |

## Sessions vs ephemeral runs (important)

`/colab-run` operates in two modes:

- **Session mode** (preferred): If `/colab-open` was called for the notebook, the run reuses the warm browser + runtime. Kernel state (imports, loaded data) persists across runs. ~3s per cell after warmup.
- **Ephemeral mode** (fallback): No session active. Each `/colab-run` spins up a new browser + new runtime (~30-60s overhead) and tears down at end. Kernel state lost between runs.

**Rule of thumb**: any time the user is going to run more than one cell, or iterate on a single cell with edits, suggest `/colab-open` first. The response includes a `via: "session" | "ephemeral"` field so you always know which path was taken.

The lock is shared: only one notebook can have an active session at a time. Trying to `/colab-run` against notebook B while a session is open for notebook A fails loud.

## The notebook-from-a-goal flow (most common)

When the user describes a notebook they want built end-to-end:

1. **Plan**: spawn `colab-planner` with the goal. It returns a JSON plan (cell list + expected outputs + runtime).
2. **Review**: show the plan summary to the user. Confirm runtime if non-cpu. (Skip review if user said `--yolo` or similar.)
3. **Create the notebook**: `/colab-new <title>` → capture the file_id.
4. **Execute**: spawn `colab-executor` with `{plan, file_id, retry_budget}`. It walks the plan, adds + runs each cell, spawns `colab-debugger` on failures within the retry budget.
5. **Report**: show the user the per-cell status table the executor returns. Highlight any failed or skipped cells.

This three-agent flow is the reason this plugin exists. Don't shortcut it for non-trivial work.

## Agent boundaries (don't blur these)

- **planner**: reads, thinks, outputs a plan. Read-only tools.
- **executor**: writes cells and runs them. Has Bash + edit access. **Does not redesign** — runs the plan as given.
- **debugger**: reads errors, proposes fixes, returns. **Does not execute or write** — that comes back to executor.

## Locking

Only one notebook can be running at a time. `/colab-run` takes a file lock at `~/.claude-colab/colab.lock`. Concurrent runs (including `/colab-selftest`) error out with `ColabBusyError` — wait for the previous run to finish.

## Output handling

- Text outputs → returned in JSON from `/colab-run`, surface to the user inline.
- Images → saved to `~/.claude-colab/runs/<file_id>/<cell_id>/*.png`. Surface paths in the chat; main Claude can `Read` them since it's multimodal.

## Drive scope

Default = `claude-colab/` folder in My Drive. Agents physically cannot see other notebooks until the user runs `/colab-scope --full`. Don't suggest widening unless the user asks.

## When things break

1. If a cell hangs or returns no output → `/colab-selftest`. If selectors drifted, file an issue.
2. If Drive API errors → `/colab-auth --force` to refresh.
3. If browser login expired → `/colab-login`.
4. If the lock is stuck (no live session) → `rm ~/.claude-colab/colab.lock` (last resort, only if you're sure).

## Quick reference: shell entrypoint

Every command shells out to `${CLAUDE_PLUGIN_ROOT}/bin/colab.py`. That launcher auto-bootstraps the venv on first run and forwards argv to `python -m scripts.cli`. You don't need to manage venv paths in command files.
