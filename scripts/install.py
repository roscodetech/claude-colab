"""One-shot installer.

Idempotent: safe to run repeatedly. Creates the bundled venv, installs Python
deps, downloads Playwright Chromium, writes the default config.

Run with the *system* Python — not the venv. Subsequent claude-colab calls go
through the venv automatically.
"""

from __future__ import annotations

import json
import subprocess
import sys
import venv
from pathlib import Path

# Allow running this file directly via `python install.py` (no package context).
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import config, paths
else:
    from . import config, paths


MIN_PY = (3, 11)


def _check_python() -> None:
    if sys.version_info < MIN_PY:
        raise SystemExit(
            f"claude-colab requires Python {MIN_PY[0]}.{MIN_PY[1]}+; "
            f"running {sys.version.split()[0]}"
        )


def _create_venv() -> None:
    if paths.venv_python().exists():
        return
    print(f"creating venv at {paths.VENV_DIR}", flush=True)
    builder = venv.EnvBuilder(with_pip=True, clear=False, upgrade_deps=True)
    builder.create(str(paths.VENV_DIR))


def _pip_install() -> None:
    pip = str(paths.venv_pip())
    req = str(paths.REQUIREMENTS_PATH)
    print("installing python deps", flush=True)
    subprocess.check_call([pip, "install", "--upgrade", "pip"])
    subprocess.check_call([pip, "install", "-r", req])


def _playwright_install() -> None:
    py = str(paths.venv_python())
    print("installing playwright chromium (~300 MB, one-time)", flush=True)
    # `playwright install chromium` downloads the browser bundle. Idempotent.
    subprocess.check_call([py, "-m", "playwright", "install", "chromium"])


def _write_default_config() -> None:
    if paths.CONFIG_PATH.exists():
        return
    config.save(dict(config.DEFAULTS))
    print(f"wrote default config to {paths.CONFIG_PATH}", flush=True)


def main() -> int:
    _check_python()
    paths.ensure_home()
    _create_venv()
    _pip_install()
    _playwright_install()
    _write_default_config()
    print(json.dumps({"status": "ok", "home": str(paths.HOME)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
