from __future__ import annotations

from openlabs.engine import _codex_hook_receipt_status


def test_missing_session_start_is_warning_when_final_stop_passes() -> None:
    error, warning = _codex_hook_receipt_status(
        {
            "hooks": {
                "schema_version": "openlabs.hook_runtime.v1",
                "session_start_count": 0,
                "stop_passed": True,
            }
        }
    )

    assert error is None
    assert warning is not None
    assert "SessionStart" in warning


def test_missing_or_failed_final_stop_remains_fatal() -> None:
    missing_error, missing_warning = _codex_hook_receipt_status({})
    failed_error, failed_warning = _codex_hook_receipt_status(
        {
            "hooks": {
                "schema_version": "openlabs.hook_runtime.v1",
                "session_start_count": 1,
                "stop_passed": False,
            }
        }
    )

    assert missing_error == "Codex lifecycle hook receipts are missing or invalid"
    assert missing_warning is None
    assert failed_error == "Codex final Stop gate receipt is incomplete"
    assert failed_warning is None
