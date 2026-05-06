"""Cross-platform launcher.

Resolves the bundled venv python (running install.py first if the venv is
missing), then re-execs scripts.cli with the same argv. This is the single
entrypoint every slash command shells out to.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Make `scripts` importable when we run install/cli from here.
sys.path.insert(0, str(PLUGIN_ROOT))

from scripts import paths  # noqa: E402


def _ensure_venv() -> Path:
    py = paths.venv_python()
    if py.exists():
        return py
    # Run install with the *system* python, then return the freshly built venv.
    print("first run — bootstrapping ~/.claude-colab/.venv (one time)", flush=True)
    install_script = PLUGIN_ROOT / "scripts" / "install.py"
    subprocess.check_call([sys.executable, str(install_script)])
    return paths.venv_python()


def main() -> int:
    py = _ensure_venv()
    argv = [str(py), "-m", "scripts.cli", *sys.argv[1:]]
    # Use exec on POSIX so signals propagate cleanly; subprocess on Windows.
    if os.name == "posix":
        os.execvpe(argv[0], argv, {**os.environ, "PYTHONPATH": str(PLUGIN_ROOT)})
        return 0  # unreachable
    return subprocess.call(argv, env={**os.environ, "PYTHONPATH": str(PLUGIN_ROOT)})


if __name__ == "__main__":
    sys.exit(main())
