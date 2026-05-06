# Contributing to claude-colab

PRs are welcome — selectors will rot when Colab ships UI changes, and that's the most useful kind of contribution. Issues and feature requests are welcome too.

## Quick start

```bash
git clone https://github.com/roscodetech/claude-colab.git
cd claude-colab
python -m venv .venv
.venv/Scripts/activate    # or source .venv/bin/activate on POSIX
pip install -r requirements.txt
pip install pytest ruff
pytest tests/
```

## Pull request checklist

Before opening a PR:

- [ ] Tests pass: `pytest tests/`
- [ ] Lint clean: `ruff check scripts/ tests/ bin/`
- [ ] Format clean: `ruff format --check scripts/ tests/ bin/` (run `ruff format ...` to fix)
- [ ] If you changed Colab DOM selectors, bump `SCHEMA_VERSION` in `scripts/selectors.py`
- [ ] If you added a new command/agent, update `skills/colab/SKILL.md`'s capability map

CI will run the same checks on every PR.

## Where to start

- **Selector fixes**: `scripts/selectors.py` is one place. Run `/colab-selftest` against your fix to verify.
- **New cell types or runtime tricks**: extend `scripts/browser.py` and `scripts/notebook.py`.
- **Agent prompt improvements**: `agents/colab-{planner,executor,debugger}.md`.
- **New slash commands**: drop a markdown file in `commands/`, add a CLI subcommand in `scripts/cli.py`.

## Approval

`main` is protected — merges require review from a code owner ([@roscoekerby](https://github.com/roscoekerby)). Open a PR from a fork; we'll review.

## Style

- Match the surrounding code's idioms.
- Comments explain *why*, not *what* (the code already says what).
- Prefer small, focused commits over a monolithic PR.

## Out of scope

This plugin is intentionally focused: drive Colab from Claude Code. Things to skip:
- Local Jupyter (different problem, lots of existing tools).
- Hosted notebook providers other than Colab (Kaggle, Sagemaker, etc.) — fork instead.
- Anything that requires bundling secrets/keys.

## License

By contributing you agree your contribution is licensed under [MIT](LICENSE).
