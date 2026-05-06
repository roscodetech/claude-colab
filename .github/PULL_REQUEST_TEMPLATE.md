<!-- Thanks for contributing! Fill in what's relevant; delete the rest. -->

## What
<!-- One-line summary of the change. -->

## Why
<!-- Bug fix? Selector breakage? New capability? Link the issue if there is one. -->

## How tested
<!-- Did you run pytest? /colab-selftest? Any manual flow worth describing? -->

## Checklist
- [ ] `pytest tests/` passes
- [ ] `ruff check scripts/ tests/ bin/` clean
- [ ] `ruff format --check scripts/ tests/ bin/` clean
- [ ] If selectors changed: bumped `SCHEMA_VERSION` in `scripts/selectors.py`
- [ ] If new command/agent: updated `skills/colab/SKILL.md`
