"""Drive API wrapper.

Scope is `drive.file` — we only see files we created or that the user
explicitly opened with this app. Safe by construction.

Folder scoping: by default everything goes inside a `claude-colab/` folder
in My Drive. The `drive_scope_full` config flag widens this; even then we
prefer creating new notebooks inside the folder unless the caller overrides.
"""

from __future__ import annotations

import io
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from . import config
from .auth import get_drive_service

NOTEBOOK_MIME = "application/vnd.google.colaboratory"
JUPYTER_MIME = "application/x-ipynb+json"
FOLDER_MIME = "application/vnd.google-apps.folder"

# Google indexes Colab notebooks under either MIME type depending on origin.
NOTEBOOK_MIMES = (NOTEBOOK_MIME, JUPYTER_MIME)


# ---------- Folder management ----------

def ensure_folder(name: str | None = None) -> str | None:
    """Find or create the scope folder. Returns folder_id, or None if scope is full Drive.

    If `name` is None, uses config.drive_scope_folder. Empty string or
    drive_scope_full=True returns None (= My Drive root, no scoping).
    """
    cfg = config.load()
    if cfg.get("drive_scope_full"):
        return None
    folder_name = name or cfg.get("drive_scope_folder")
    if not folder_name:
        return None

    svc = get_drive_service()
    q = (
        f"name = '{folder_name}' and mimeType = '{FOLDER_MIME}' "
        "and trashed = false"
    )
    res = svc.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    # Create it.
    meta = {"name": folder_name, "mimeType": FOLDER_MIME}
    created = svc.files().create(body=meta, fields="id").execute()
    return created["id"]


# ---------- Notebook CRUD ----------

def list_notebooks(
    folder_id: str | None = None,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """List notebooks in the given folder (default: scope folder)."""
    svc = get_drive_service()
    if folder_id is None:
        folder_id = ensure_folder()

    mime_clause = " or ".join(f"mimeType = '{m}'" for m in NOTEBOOK_MIMES)
    parts = [f"({mime_clause})", "trashed = false"]
    if folder_id:
        parts.append(f"'{folder_id}' in parents")
    q = " and ".join(parts)

    res = svc.files().list(
        q=q,
        fields="files(id, name, modifiedTime, headRevisionId, webViewLink, mimeType)",
        pageSize=page_size,
        orderBy="modifiedTime desc",
    ).execute()
    return res.get("files", [])


def create_notebook(name: str, folder_id: str | None = None, content_bytes: bytes | None = None) -> dict[str, Any]:
    """Create a new Colab notebook. Returns the file metadata dict."""
    svc = get_drive_service()
    if folder_id is None:
        folder_id = ensure_folder()

    if not name.endswith(".ipynb"):
        name = f"{name}.ipynb"

    meta: dict[str, Any] = {"name": name, "mimeType": NOTEBOOK_MIME}
    if folder_id:
        meta["parents"] = [folder_id]

    if content_bytes is None:
        # Empty notebook — single empty code cell, nbformat 4.5.
        from .notebook import empty_notebook_bytes
        content_bytes = empty_notebook_bytes()

    media = MediaIoBaseUpload(
        io.BytesIO(content_bytes),
        mimetype=JUPYTER_MIME,
        resumable=False,
    )
    created = svc.files().create(
        body=meta,
        media_body=media,
        fields="id, name, modifiedTime, headRevisionId, webViewLink",
    ).execute()
    return created


def get_notebook_bytes(file_id: str) -> bytes:
    """Download the raw .ipynb JSON bytes."""
    svc = get_drive_service()
    request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def update_notebook(
    file_id: str,
    content_bytes: bytes,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Upload new content for an existing notebook.

    If `expected_revision` is provided, the upload aborts when Drive's current
    headRevisionId differs (someone else edited it). Caller should retry after
    re-fetching.
    """
    svc = get_drive_service()

    if expected_revision is not None:
        meta = svc.files().get(fileId=file_id, fields="headRevisionId").execute()
        actual = meta.get("headRevisionId")
        if actual != expected_revision:
            raise RevisionConflict(
                f"Drive revision changed: expected {expected_revision}, got {actual}"
            )

    media = MediaIoBaseUpload(
        io.BytesIO(content_bytes),
        mimetype=JUPYTER_MIME,
        resumable=False,
    )
    updated = svc.files().update(
        fileId=file_id,
        media_body=media,
        fields="id, name, modifiedTime, headRevisionId",
    ).execute()
    return updated


def delete_notebook(file_id: str, hard: bool = False) -> None:
    """Trash by default; pass hard=True for permanent delete."""
    svc = get_drive_service()
    if hard:
        svc.files().delete(fileId=file_id).execute()
    else:
        svc.files().update(fileId=file_id, body={"trashed": True}).execute()


def get_metadata(file_id: str) -> dict[str, Any]:
    svc = get_drive_service()
    return svc.files().get(
        fileId=file_id,
        fields="id, name, modifiedTime, headRevisionId, webViewLink, parents, mimeType",
    ).execute()


def find_by_name(name: str, folder_id: str | None = None) -> dict[str, Any] | None:
    """Find a notebook by exact name in the given folder."""
    svc = get_drive_service()
    if folder_id is None:
        folder_id = ensure_folder()
    if not name.endswith(".ipynb"):
        name = f"{name}.ipynb"

    parts = [f"name = '{name}'", "trashed = false"]
    if folder_id:
        parts.append(f"'{folder_id}' in parents")
    q = " and ".join(parts)
    res = svc.files().list(q=q, fields="files(id, name, headRevisionId)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0] if files else None


class RevisionConflict(Exception):
    """Raised when an optimistic-locking update detects a remote edit."""
