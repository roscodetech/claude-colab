# claude-colab — Phase 1 Plan

**Goal**: Ship a functional Claude Code plugin that lets agents CRUD Google Colab notebooks, drive a Chrome browser to execute cells, and capture text+image output. Three subagents (planner/executor/debugger). Anthropic marketplace target.

**Locked decisions**
- Plugin (not single skill); marketplace target = Anthropic.
- Hybrid: Drive API + nbformat + Playwright/Chromium.
- Bundled venv installer at `~/.claude-colab/.venv`. Auto-create on first command.
- Output: text + images saved to `~/.claude-colab/runs/<nb>/<cell>/`. Wizard asks once.
- Drive scope default: `claude-colab/` folder; `/colab-scope` to widen.
- Per-cell run is Phase 1.
- Three subagents: planner / executor / debugger. Main Claude orchestrates.
- One notebook at a time. Debugger auto-retry default 2, user-configurable via `~/.claude-colab/config.json`.

---

## Phase 1 — Build

### 1. Scaffolding
- [ ] `claude-colab/.claude-plugin/plugin.json`
- [ ] `claude-colab/README.md` — install, auth, quickstart
- [ ] `claude-colab/requirements.txt` — google-api-python-client, google-auth-oauthlib, nbformat, playwright, pillow
- [ ] `claude-colab/LICENSE` — MIT
- [ ] `claude-colab/.gitignore`

### 2. Installer (`scripts/install.py`)
- [ ] Detect Python ≥ 3.11; abort with clear message if missing
- [ ] Create `~/.claude-colab/.venv`
- [ ] `pip install -r requirements.txt` into venv
- [ ] `playwright install chromium`
- [ ] Write default `~/.claude-colab/config.json`:
  ```json
  {
    "drive_scope_folder": "claude-colab",
    "drive_scope_full": false,
    "save_images": true,
    "image_dir": "~/.claude-colab/runs",
    "debugger_max_retries": 2,
    "browser_profile_dir": "~/.claude-colab/chrome-profile",
    "default_runtime": "cpu"
  }
  ```
- [ ] Idempotent — re-run safe

### 3. Auth (`scripts/auth.py`)
- [ ] OAuth 2.0 installed-app flow for Drive
- [ ] Store refresh token at `~/.claude-colab/drive_token.json` (chmod 600 on POSIX)
- [ ] Helper: `get_drive_service()` → returns authed Drive v3 client
- [ ] Browser login: launch persistent Chromium at `colab.research.google.com`, wait for user signin, close on detection of authed cookie

### 4. Drive layer (`scripts/drive.py`)
- [ ] `list_notebooks(folder=None) -> [{id, name, modifiedTime, webViewLink}]`
- [ ] `create_notebook(name, folder=None) -> file_id`
- [ ] `get_notebook(file_id) -> bytes` (downloads .ipynb)
- [ ] `update_notebook(file_id, content_bytes, expected_revision=None)` — revision check
- [ ] `delete_notebook(file_id)`
- [ ] `ensure_folder(name) -> folder_id` — creates `claude-colab/` if missing
- [ ] `share(file_id, email, role)` — Phase 2; stub now

### 5. Notebook layer (`scripts/notebook.py`)
- [ ] `read(file_id) -> nbformat.NotebookNode` (uses Drive layer + nbformat)
- [ ] `write(file_id, nb)` — bumps Drive revision
- [ ] `get_cell(nb, cell_id|idx) -> Cell`
- [ ] `add_cell(nb, source, cell_type='code', after=None) -> cell_id`
- [ ] `edit_cell(nb, cell_id, source)`
- [ ] `delete_cell(nb, cell_id)`
- [ ] `reorder(nb, [cell_ids])`
- [ ] `summarize(nb) -> str` — compact view for agent context (id, type, first 2 lines)
- [ ] All cells use stable nbformat 4.5 ids

### 6. Browser layer (`scripts/browser.py`)
- [ ] `Browser` class with persistent Chromium context (profile dir from config)
- [ ] `open_notebook(file_id) -> Page` — navigates to `colab.research.google.com/drive/<id>`
- [ ] `connect_runtime(kind='cpu'|'gpu'|'tpu')` — clicks Connect, picks runtime
- [ ] `run_cell(cell_id) -> RunResult` — finds cell by data-cell-id, clicks run, waits for completion, captures output
- [ ] `run_all() -> [RunResult]`
- [ ] `RunResult` = `{cell_id, status, stdout, stderr, images: [path], duration_ms}`
- [ ] Image extraction: download `<img>` blobs and PNG output cells, save to image_dir
- [ ] Error detection: parse Colab error styling, extract traceback text
- [ ] Selectors centralized in `scripts/selectors.py` so they're easy to fix when Colab UI changes

### 7. CLI (`scripts/cli.py`)
- [ ] Single entrypoint dispatched from commands
- [ ] Subcommands: `auth`, `login`, `init`, `new`, `open`, `list`, `run`, `edit`, `output`, `scope`
- [ ] Output JSON for agent consumption, human text when `--human`

### 8. Commands (markdown files in `claude-colab/commands/`)
- [ ] `colab-auth.md` — runs auth.py Drive OAuth
- [ ] `colab-login.md` — runs browser login
- [ ] `colab-init.md` — runs first-time wizard (image saving + scope choice)
- [ ] `colab-new.md` — create notebook from template
- [ ] `colab-list.md` — list notebooks in scope
- [ ] `colab-open.md` — open in headed Chromium
- [ ] `colab-run.md` — run cell(s) by id or "all"
- [ ] `colab-edit.md` — add/edit/delete cell
- [ ] `colab-output.md` — fetch last run output for cell
- [ ] `colab-scope.md` — change Drive scope

### 9. Subagents (markdown files in `claude-colab/agents/`)
- [ ] `colab-planner.md` — frontmatter: tools=Read,Grep,WebSearch; model=sonnet
  - Input: goal + optional existing notebook id
  - Output: ordered list of cells with type, source, expected_output_kind
- [ ] `colab-executor.md` — frontmatter: tools=Read,Write,Edit,Bash; model=sonnet
  - Input: notebook id + plan + retry budget
  - Walks plan, calls cli.py for each cell, captures result, on failure spawns debugger
  - Output: per-cell status report
- [ ] `colab-debugger.md` — frontmatter: tools=Read,Edit,Bash,WebSearch; model=sonnet
  - Input: failing cell + error + last N cell outputs
  - Output: proposed cell rewrite + reason; never executes itself
  - Cap retries at config.debugger_max_retries

### 10. Skill entry (`claude-colab/skills/colab/SKILL.md`)
- [ ] Top-level orientation: when to use, command list, agent list, common flows
- [ ] Includes a "Recipe: build a notebook from a goal" example walking the planner→executor→debugger loop

### 11. Tests (`claude-colab/tests/`)
- [ ] `test_notebook.py` — cell CRUD round-trip with nbformat (no Drive)
- [ ] `test_drive.py` — mocked Drive API
- [ ] `test_browser.py` — Playwright recorded HAR or skipped without auth
- [ ] `test_cli.py` — subprocess invocations, --human and JSON modes
- [ ] CI script — `node tests/run-all.js`-style or `pytest`

### 12. Docs
- [ ] README — install, auth, scope, first run, troubleshooting (Playwright on Win/Mac/Linux)
- [ ] CONTRIBUTING — selector update process when Colab UI changes
- [ ] Marketplace listing copy

### 13. Verify
- [ ] Out-of-the-box flow: fresh machine → install plugin → `/colab-init` → `/colab-auth` → `/colab-login` → `/colab-new "test"` → `/colab-run all` → see output
- [ ] Subagent flow: ask main Claude "build a notebook that loads iris and trains logistic regression" → planner produces plan → executor runs → debugger fixes any errors → verify cells exist and ran

---

## Phase 2 (deferred — not in this build)
- Form fields, GPU/TPU selection UX, Drive mount helper, share/permissions, multi-notebook concurrency

## Phase 3 (deferred)
- Direct kernel exec via `jupyter_http_over_ws` websocket

## Phase 4 (deferred)
- Marketplace publish

---

## Open risk / watch-list
- **Colab DOM changes**: selectors will rot. Mitigation: centralize in `selectors.py`, version-tag, add a `colab-selftest` command that runs a tiny smoke notebook and reports broken selectors.
- **Auth refresh**: Drive token expiry handled by google-auth; browser cookies handled by persistent profile. If browser login expires, `colab-login` re-prompts.
- **Windows path quirks**: profile dir, image dir, venv. Use `pathlib.Path.expanduser()` everywhere.
- **Playwright install size**: ~300MB Chromium. Document this in README.

## Review (Phase 1 — built)

**Built**: full plugin scaffold at `C:\ROSCODE TECH\Utility Apps\claude-colab\` — 5 markdown agents/skills, 13 slash commands, 9 Python modules, 5 test files (35 tests, all passing).

**Files added**:
- `.claude-plugin/plugin.json`, `README.md`, `LICENSE`, `requirements.txt`, `.gitignore`
- `bin/colab.py` — venv-bootstrapping launcher
- `scripts/{paths,config,install,auth,drive,notebook,browser,selectors,cli,selftest}.py`
- `commands/colab-{init,auth,login,list,new,open,show,edit,run,output,delete,scope,selftest}.md`
- `agents/colab-{planner,executor,debugger}.md`
- `skills/colab/SKILL.md`
- `tests/{conftest,test_notebook,test_config,test_drive_mocked,test_cli,test_browser_lock}.py`

**Decisions worth flagging**:
1. **BYO OAuth client.** Public plugins that ship a shared Drive OAuth client risk Google rate-limiting or suspending the entire user base. Two-minute setup is the right tradeoff. README walks users through it.
2. **`drive.file` scope only** — agents physically cannot see Drive files outside what the user explicitly opens with this app. Stronger than the folder filter.
3. **Path-constant binding fix.** First test run revealed `from .paths import X` binds at import time, so the fixture's monkeypatch didn't propagate. Fixed by switching all path-constant accesses to `paths.X` via module reference. Functions (`ensure_home`) stay imported by name since they reference module-level names internally and pick up patches at call time.
4. **Centralized selectors** in `scripts/selectors.py` with a `SCHEMA_VERSION` string and a `colab-selftest` canary. Colab UI shifts every few months; this is the only file to edit when it does.
5. **Agent boundaries enforced via tools.** Planner has no Write or Bash. Debugger has no execution. Only executor can both write and run — and only inside the file_id it was given. Boundaries by capability, not by rules-the-agent-might-ignore.

**Verification**:
- 35/35 pytest tests pass.
- All 9 Python modules import cleanly.
- CLI `--help` dispatches all 13 subcommands correctly.

**Not yet done (intentional, deferred to Phase 2+)**:
- Live Drive API integration test (needs OAuth setup on a test project).
- Live Colab DOM test (needs browser login + stable UI).
- Form fields, GPU/TPU UI flow, Drive mount helper, multi-notebook concurrency.
- Direct kernel exec via `jupyter_http_over_ws`.
- Marketplace submission.

**Lessons learned** (added to global lessons file as separate items):
- When using `monkeypatch.setattr(module, "CONSTANT", ...)`, downstream modules must access via `module.CONSTANT` not `from module import CONSTANT` — the latter binds at import time.
- Validate CLI args before any IO call. Fail-fast saves a network round-trip and gives clearer error messages.
