"""HTTP classification, accounting, and completeness tests for Sciverse."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.sciverse import (  # noqa: E402
    SciverseClient,
    SciverseDocumentTruncated,
    SciverseFetchUnavailable,
)


def _client(tmp_path: Path) -> SciverseClient:
    return SciverseClient(
        token="test", cache_dir=tmp_path, min_interval=0, max_retries=1
    )


def test_content_not_found_is_permanent_unavailable(monkeypatch, tmp_path):
    payload = json.dumps({"code": "CONTENT_NOT_FOUND"}).encode()

    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example/content", 404, "missing", {}, io.BytesIO(payload)
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)
    client = _client(tmp_path)
    with pytest.raises(SciverseFetchUnavailable):
        client.read_content("absent")
    assert client.calls_made == 1
    assert client.successful_calls == 0


def test_failed_attempts_count_toward_api_calls(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example/content", 403, "forbidden", {}, io.BytesIO(b"no")
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)
    client = _client(tmp_path)
    with pytest.raises(Exception):
        client.read_content("forbidden")
    assert client.stats()["api_calls"] == 1


def test_full_document_refuses_silent_safety_limit(tmp_path, monkeypatch):
    client = _client(tmp_path)
    pages = iter(
        [
            {"text": "abcdef", "more": True, "next_offset": 6},
            {"text": "ghijkl", "more": True, "next_offset": 12},
        ]
    )
    monkeypatch.setattr(client, "read_content", lambda *_args, **_kwargs: next(pages))
    with pytest.raises(SciverseDocumentTruncated, match="max_chars"):
        client.read_full_document("large", max_chars=10)


def test_full_document_rejects_nonadvancing_cursor(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.setattr(
        client,
        "read_content",
        lambda *_args, **_kwargs: {"text": "abc", "more": True, "next_offset": 0},
    )
    with pytest.raises(SciverseDocumentTruncated, match="next_offset"):
        client.read_full_document("broken")
