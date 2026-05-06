---
description: Run a canary notebook (print, plot, error) to catch broken Colab UI selectors before they bite real workflows
---

# /colab-selftest

Creates a throwaway notebook, runs three canary cells, validates that text capture, image capture, and error detection all still work. Hard-deletes the notebook afterward.

Takes the run-lock — don't fire while another notebook is executing.

## Action

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/colab.py" selftest
```

## Interpret the output

- `status: ok` and all checks `ok: true` → selectors current, you're good.
- `status: selectors_drifted` → one or more checks failed. Each `check.name` maps to a known capability (drive_crud, browser_run_all, stdout_capture, image_capture, error_detection). File an issue with the report attached.
- `status: error` → the test itself blew up before completing. Show the error to the user.

## When to run

- After a Colab UI update (Google ships these silently).
- Before a long workflow if you've not used the plugin in a while.
- Whenever a real run mysteriously hangs or produces no output.
