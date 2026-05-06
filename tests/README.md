# tests

```bash
# from plugin root
pytest tests/
```

## Coverage

- `test_notebook.py` — cell CRUD via nbformat (no network)
- `test_config.py` — config defaults + merge behavior
- `test_drive_mocked.py` — Drive client query construction + revision conflicts
- `test_cli.py` — argparse routing + JSON output shape
- `test_browser_lock.py` — file-lock contract (one notebook at a time)

## What's NOT tested here

- Real Drive API calls (need OAuth + a test project)
- Real Chromium / Colab DOM (need browser login + Colab UI stable)

For end-to-end validation, run `/colab-selftest` after auth + login. That's the canary.

## Why pytest?

Plugin uses Python; tests stay Python. No JS test runner needed.
