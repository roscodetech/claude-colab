# claude-colab

Drive Google Colab from Claude Code. CRUD notebooks via the Drive API, run cells via a headed Chromium, capture text and image output. Three subagents (planner / executor / debugger) for end-to-end notebook authoring.

## What this gives you

- `/colab-new`, `/colab-list`, `/colab-show`, `/colab-edit`, `/colab-delete` — notebook + cell CRUD via Drive API
- `/colab-open` — spawn a persistent session daemon (warm runtime, kernel state preserved across cells)
- `/colab-run` — run a cell or all cells; uses the active session if open, ephemeral otherwise
- `/colab-status`, `/colab-close` — inspect or shut down the active session
- `/colab-output` — re-fetch the last run's output for any cell
- `/colab-scope` — manage Drive scope (OAuth + folder filter)
- `/colab-selftest` — canary notebook that flags broken Colab UI selectors before they bite you
- Subagents `colab-planner`, `colab-executor`, `colab-debugger` — say "build me a notebook that does X" and they handle plan → run → fix loops
- Out-of-the-box install: bundled venv, auto Playwright Chromium download, one wizard run

## Install

```
/plugin install claude-colab
/colab-init        # one-time wizard: image saving, Drive scope, retry budget
/colab-auth        # one-time Drive OAuth (browser opens, you sign in once)
/colab-login       # one-time Colab browser login (cookies persisted)
```

Requires Python 3.11+ on PATH. First run creates `~/.claude-colab/.venv` and downloads Chromium (~300 MB).

OAuth client setup (one-time, ~2 min): see `/colab-auth` output for Cloud Console steps. We don't ship a shared OAuth client; one shared client used at scale gets rate-limited or suspended by Google.

## Defaults you can change

| Setting | Default | Where |
|---|---|---|
| OAuth scope | `file` (only files we created) | `/colab-scope --oauth full` to widen |
| Drive folder filter | `claude-colab/` only | `/colab-scope --full` to lift |
| Save plot images to disk | yes | `~/.claude-colab/config.json` |
| Image dir | `~/.claude-colab/runs/` | config |
| Debugger auto-retries | 2 | config or `--retries N` on `/colab-run` |
| Default runtime | CPU | config or `--runtime gpu` on `/colab-open` |

## Recipe — iterative cell debugging (the main reason this exists)

```
/colab-open <FILE_ID>          # warm browser + runtime, daemon stays running
/colab-run --cell <CELL_ID>    # see output / error
/colab-edit ... edit --cell <CELL_ID> --source-file fix.py
/colab-run --cell <CELL_ID>    # ~3-10s after warmup; kernel state preserved
/colab-close                   # done — releases the lock
```

Without `/colab-open`, every `/colab-run` spins up a fresh browser + new Colab runtime (~30-60s overhead per call) and **loses kernel state** between calls.

## Recipe — build a notebook from a goal

```
> Build a Colab notebook that loads the iris dataset and trains a logistic regression classifier with a confusion matrix plot.

  → main Claude calls colab-planner    (read-only, produces cell list)
  → user nods (or --yolo)
  → colab-executor opens a session, runs cells one at a time
  → on error, colab-debugger proposes a fix, executor retries (max 2)
  → executor closes the session, returns per-cell status report
```

## Safety notes

- Default Drive scope is restricted to a single `claude-colab/` folder — agents cannot see or touch the rest of your Drive until you widen scope (`/colab-scope --full`).
- Default OAuth scope is `drive.file` — Google enforces that we only see files this app created. To edit notebooks created via the Colab UI you must run `/colab-scope --oauth full` and re-auth.
- Browser uses an isolated profile at `~/.claude-colab/chrome-profile/` — your real Chrome profile is never touched.
- Drive token is chmod 600 on POSIX. Stored at `~/.claude-colab/drive_token.json`.
- One notebook session can be open at a time (mutex via session.json + PID liveness).

## Architecture and known limitations

This plugin **drives Colab via browser automation** (Playwright + headed Chromium). That has trade-offs you should know about:

**The good:**
- Full notebook CRUD via Drive API — list, create, edit, delete any notebook in your Drive (with `--oauth full`)
- The planner→executor→debugger flow lets agents author entire notebooks from a one-line goal
- Persistent session daemon means iterative cell runs share kernel state (~7× speedup vs cold)
- Default-narrow OAuth + folder scope is opt-out; agents can't reach into your wider Drive without explicit consent

**The fragile:**
- Cell execution depends on Colab's DOM. Google ships UI changes; selectors break; we patch. Run `/colab-selftest` after Colab updates — if any check fails, file an issue.
- Output capture for some rich types (cell-level Markdown rendering, custom widgets) is incomplete. Plain stdout, errors, plots, and DataFrames all work; novel display_data types may not.
- Browser startup is ~10-15s. The session daemon amortizes this across many runs but the first `/colab-open` always pays it.
- Windows-specific: Chromium subprocesses inherit file handles, which is why the daemon uses session.json + PID liveness as its mutex (FileLock alone gets stuck behind orphaned Chrome).
- GPU/TPU runtime selection is implemented but lightly tested in the wild.

**Alternatives you should know about:**
- [`ali/claude-colab`](https://github.com/ali/claude-colab) — runs Claude Code *inside* a Colab notebook (terminal cell). Different problem space: best when you want Claude to live where the GPU is, not when you want to author/edit notebooks from outside.
- [Lakshmi Sravya's claude-colab (dev.to)](https://dev.to/lakshmisravyavedantham/i-built-a-tool-so-claude-code-can-use-my-colab-gpu-4hoi) — Flask-in-Colab + Cloudflare tunnel + MCP server. More robust execution path, requires bootstrapping a bridge inside each notebook.
- An "official MCP server for Colab" was announced April 2026 (per Anthropic's autocomplete-real-world-ai blog). If you need execution-only and don't care about plugin-style notebook editing, that's likely simpler.

**Where this plugin is the right fit:**
- You want Claude to author and edit *existing* notebooks in your Drive — not just execute code in a sandbox
- You want the planner→executor→debugger orchestration for end-to-end notebook construction
- You want default-narrow Drive scope as a safety property
- You're OK with browser automation as the execution channel (selectors will rot occasionally; selftest catches drift)

## Troubleshooting

- **"playwright not installed"** — re-run `/colab-init`, it installs Chromium.
- **"Drive auth failed"** — re-run `/colab-auth --force`. If it still fails, delete `~/.claude-colab/drive_token.json` and try again.
- **"Selector not found" / cell run hangs** — Colab UI shifted. Run `/colab-selftest` and file an issue with the JSON report.
- **Cell ran but stdout is empty** — could be that the cell emitted via `display_data` (DataFrames, custom reprs) which lives in an iframe. PR #6 added rich-text capture for this; if it's still empty, file an issue with the cell source.
- **`ColabBusyError` on /colab-open or /colab-run** — another session is active. `/colab-status` to inspect, `/colab-close` to release. If status says "no active session" but you still get the error, kill any leftover Playwright Chromium processes (`Get-Process chrome | Where { $_.Path -match 'ms-playwright' } | Stop-Process` on Windows) and remove `~/.claude-colab/colab.lock` and `~/.claude-colab/session.json`.
- **Session goes silent for minutes** — `tail -f ~/.claude-colab/session.log` for heartbeat lines (`[heartbeat] cell X running for Ys`). If silent there too, the daemon may be stuck — `/colab-close` to force-kill.

## Layout

```
claude-colab/
├── .claude-plugin/plugin.json
├── skills/colab/SKILL.md          # main entrypoint
├── commands/                      # /colab-* slash commands
├── agents/                        # planner, executor, debugger
├── scripts/                       # python implementation
│   ├── browser.py                 # Playwright-driven cell execution
│   ├── drive.py                   # Drive API CRUD
│   ├── notebook.py                # nbformat cell CRUD
│   ├── session_daemon.py          # persistent-session daemon
│   ├── session_client.py          # client side of IPC protocol
│   ├── selectors.py               # ALL the brittle Colab DOM selectors
│   └── selftest.py                # canary notebook for selector drift
└── tests/                         # offline unit tests
```

MIT licensed. PRs welcome — selectors will rot, contributions to keep them current especially appreciated. See [CONTRIBUTING.md](CONTRIBUTING.md).
