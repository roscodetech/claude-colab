"""Authentication.

Two independent flows:
1. Drive API — OAuth 2.0 installed-app flow. Refresh token persisted.
2. Colab browser — persistent Chromium profile; user signs in once, cookies stay.

The Drive client ID file is *user-supplied*. Google does not allow shipping a
single OAuth client across redistributed installs without putting it in trust
review, so we ask the user to drop their own credentials at
~/.claude-colab/drive_credentials.json. The README walks through this in <2 min.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import paths as _paths
from .paths import ensure_home

# Drive scopes — file-level only (we only touch files we created or that the
# user explicitly opens). Avoids the much scarier `drive` (full Drive) scope.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


# ---------- Drive OAuth ----------

def _load_credentials() -> Credentials | None:
    if not _paths.DRIVE_TOKEN_PATH.exists():
        return None
    with _paths.DRIVE_TOKEN_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Credentials.from_authorized_user_info(data, SCOPES)


def _save_credentials(creds: Credentials) -> None:
    ensure_home()
    with _paths.DRIVE_TOKEN_PATH.open("w", encoding="utf-8") as f:
        f.write(creds.to_json())
    if os.name == "posix":
        os.chmod(_paths.DRIVE_TOKEN_PATH, 0o600)


def authorize_drive(force: bool = False) -> Credentials:
    """Run installed-app OAuth flow. Re-uses refresh token unless force=True."""
    ensure_home()

    if not force:
        creds = _load_credentials()
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds

    if not _paths.DRIVE_CREDENTIALS_PATH.exists():
        raise SystemExit(
            f"Missing OAuth client at {_paths.DRIVE_CREDENTIALS_PATH}.\n\n"
            "Quick setup (one time, ~2 min):\n"
            "  1. https://console.cloud.google.com/ → create or pick a project\n"
            "  2. Enable the Google Drive API\n"
            "  3. APIs & Services → Credentials → Create OAuth client ID\n"
            "     → Application type: Desktop app\n"
            "  4. Download JSON, save as the path above\n"
            "Then re-run /colab-auth."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(_paths.DRIVE_CREDENTIALS_PATH), SCOPES
    )
    # port=0 → OS picks a free port; flow opens system browser, runs a tiny
    # local server to catch the redirect. No manual code-paste.
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def get_drive_service() -> Any:
    """Return an authed Drive v3 client. Raises if not yet authorized."""
    creds = authorize_drive(force=False)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---------- Colab browser login ----------

# Inline import — Playwright is heavy and only needed for browser login.
# Keeps `colab-auth` (Drive only) snappy.
def login_browser(timeout_sec: int = 300) -> dict[str, Any]:
    """Open Colab in a persistent Chromium profile and wait for sign-in.

    Detects success by polling for a Drive cookie. User can also close the
    window manually once they're signed in.
    """
    from playwright.sync_api import sync_playwright

    ensure_home()
    _paths.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(_paths.BROWSER_PROFILE_DIR),
            headless=False,
            channel="chromium",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto("https://colab.research.google.com/", wait_until="domcontentloaded")

        # Poll for an authed session. Colab redirects unauth'd users to a sign-in
        # landing; once authed, the URL stays at /colab... and Drive cookies appear.
        import time

        start = time.time()
        ok = False
        while time.time() - start < timeout_sec:
            cookies = ctx.cookies("https://drive.google.com")
            if any(c["name"] in ("SID", "SSID", "HSID") for c in cookies):
                ok = True
                break
            time.sleep(2)
        ctx.close()
        return {"status": "ok" if ok else "timeout", "elapsed_sec": int(time.time() - start)}


if __name__ == "__main__":
    # Allow `python -m scripts.auth drive` / `... browser` for manual testing.
    mode = sys.argv[1] if len(sys.argv) > 1 else "drive"
    if mode == "drive":
        creds = authorize_drive(force="--force" in sys.argv)
        print(json.dumps({"status": "ok", "scopes": list(creds.scopes or [])}))
    elif mode == "browser":
        print(json.dumps(login_browser()))
    else:
        raise SystemExit(f"unknown mode: {mode}")
