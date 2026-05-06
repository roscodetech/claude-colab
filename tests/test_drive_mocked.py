"""Drive layer with the API client mocked.

We're testing query construction, response parsing, and revision-conflict
detection — not Google's API itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts import drive


@pytest.fixture
def mock_service():
    """Patch get_drive_service() to return a controllable mock."""
    with patch.object(drive, "get_drive_service") as get_svc:
        svc = MagicMock()
        get_svc.return_value = svc
        yield svc


def test_list_notebooks_filters_by_folder_and_mime(mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [
            {
                "id": "abc",
                "name": "x.ipynb",
                "modifiedTime": "now",
                "headRevisionId": "r1",
                "webViewLink": "u",
                "mimeType": "application/x-ipynb+json",
            }
        ]
    }
    # Pre-prime ensure_folder by configuring mock for list call (folder lookup).
    mock_service.files().list().execute.side_effect = [
        {"files": [{"id": "FOLDER_ID", "name": "claude-colab"}]},  # ensure_folder call
        {
            "files": [
                {
                    "id": "abc",
                    "name": "x.ipynb",
                    "modifiedTime": "now",
                    "headRevisionId": "r1",
                    "webViewLink": "u",
                    "mimeType": "application/x-ipynb+json",
                }
            ]
        },
    ]

    files = drive.list_notebooks()
    assert len(files) == 1
    assert files[0]["id"] == "abc"


def test_create_notebook_adds_ipynb_extension(mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [{"id": "FOLDER_ID", "name": "claude-colab"}]
    }
    mock_service.files().create().execute.return_value = {
        "id": "newid",
        "name": "thing.ipynb",
        "modifiedTime": "now",
        "headRevisionId": "r1",
        "webViewLink": "u",
    }

    res = drive.create_notebook("thing")
    # Inspect the body passed to create() — name should have .ipynb appended
    create_call = [c for c in mock_service.files().create.call_args_list if c.kwargs.get("body")]
    assert any(c.kwargs["body"]["name"] == "thing.ipynb" for c in create_call)
    assert res["id"] == "newid"


def test_update_with_matching_revision_succeeds(mock_service):
    mock_service.files().get().execute.return_value = {"headRevisionId": "r1"}
    mock_service.files().update().execute.return_value = {"id": "f", "headRevisionId": "r2"}

    out = drive.update_notebook("f", b"{}", expected_revision="r1")
    assert out["headRevisionId"] == "r2"


def test_update_with_stale_revision_raises(mock_service):
    mock_service.files().get().execute.return_value = {"headRevisionId": "r2"}
    with pytest.raises(drive.RevisionConflict):
        drive.update_notebook("f", b"{}", expected_revision="r1")


def test_delete_default_is_trash_not_hard(mock_service):
    drive.delete_notebook("f")
    # update() called with trashed=True; delete() not called
    update_calls = mock_service.files().update.call_args_list
    assert any(c.kwargs.get("body") == {"trashed": True} for c in update_calls)
    mock_service.files().delete.assert_not_called()


def test_delete_hard_calls_delete(mock_service):
    drive.delete_notebook("f", hard=True)
    mock_service.files().delete.assert_called()
