# claude-colab

Drive Google Colab from Claude Code. CRUD notebooks via the Drive API, run cells via a headed Chromium, capture text and image output. Three subagents (planner / executor / debugger) for end-to-end notebook authoring.

## What this gives you

- `/colab-new`, `/colab-list`, `/colab-open`, `/colab-edit`, `/colab-delete` — notebook + cell CRUD via Drive API
- `/colab-run` — run a single cell or all cells; output captured back into the conversation
- `/colab-output` — re-fetch the last run's output for any cell
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

## Defaults you can change

| Setting | Default | Where |
|---|---|---|
| Drive scope | `claude-colab/` folder only | `/colab-scope` |
| Save plot images to disk | yes | `~/.claude-colab/config.json` |
| Image dir | `~/.claude-colab/runs/` | config |
| Debugger auto-retries | 2 | config or `--retries N` on `/colab-run` |
| Default runtime | CPU | config or `--runtime gpu` on `/colab-run` |

## Recipe — build a notebook from a goal

```
> Build a Colab notebook that loads the iris dataset and trains a logistic regression classifier with a confusion matrix plot.

  → main Claude calls colab-planner    (read-only, produces cell list)
  → user nods (or --yolo)
  → colab-executor runs cells one at a time
  → on error, colab-debugger proposes a fix, executor retries (max 2)
  → final per-cell status report back in the chat
```

## Safety notes

- Default Drive scope is restricted to a single `claude-colab/` folder — agents cannot see or touch the rest of your Drive until you widen scope.
- Browser uses an isolated profile at `~/.claude-colab/chrome-profile/` — your real Chrome profile is never touched.
- Drive token (`~/.claude-colab/drive_token.json`) is chmod 600 on POSIX.
- One notebook can be running at a time. Concurrent run attempts error out cleanly.

## Troubleshooting

- **"playwright not installed"** — re-run `/colab-init`, it installs Chromium.
- **"Drive auth failed"** — re-run `/colab-auth`. If it still fails, delete `~/.claude-colab/drive_token.json` and try again.
- **"Selector not found" / cell run hangs** — Colab UI shifted. Run `/colab-selftest` and file an issue with the report.

## Layout

```
claude-colab/
├── .claude-plugin/plugin.json
├── skills/colab/SKILL.md       # main entrypoint
├── commands/                   # /colab-* slash commands
├── agents/                     # planner, executor, debugger
├── scripts/                    # python implementation
└── tests/
```

MIT licensed. PRs welcome — selectors will rot, contributions to keep them current especially appreciated.
