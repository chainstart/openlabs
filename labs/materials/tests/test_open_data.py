from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.open_data import CachedHTTPClient, OpenDataError


class _Response:
    def __init__(self, body: str):
        self.body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_response_is_cached_and_hash_verified(tmp_path):
    calls = []

    def opener(request, *, timeout):
        calls.append((request.full_url, timeout))
        return _Response('{"ok": true}')

    client = CachedHTTPClient(
        cache_dir=tmp_path,
        user_agent="test",
        min_interval_seconds=0,
        opener=opener,
    )
    first, first_artifact = client.get_json("https://example.test/data")
    second, second_artifact = client.get_json("https://example.test/data")
    assert first == second == {"ok": True}
    assert len(calls) == 1
    assert not first_artifact.from_cache
    assert second_artifact.from_cache
    assert first_artifact.sha256 == second_artifact.sha256


def test_modified_cache_is_rejected(tmp_path):
    client = CachedHTTPClient(
        cache_dir=tmp_path,
        user_agent="test",
        min_interval_seconds=0,
        opener=lambda *_args, **_kwargs: _Response("original"),
    )
    artifact = client.get_text("https://example.test/data")
    artifact.content_path.write_text("changed", encoding="utf-8")
    with pytest.raises(OpenDataError, match="provenance mismatch"):
        client.get_text("https://example.test/data")


def test_nonretryable_http_error_fails_immediately(tmp_path):
    def opener(request, *, timeout):
        del timeout
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "not found",
            {},
            io.BytesIO(b"missing"),
        )

    client = CachedHTTPClient(
        cache_dir=tmp_path,
        user_agent="test",
        min_interval_seconds=0,
        max_retries=3,
        opener=opener,
    )
    with pytest.raises(OpenDataError, match="HTTP 404"):
        client.get_text("https://example.test/missing")


def test_invalid_json_is_rejected(tmp_path):
    client = CachedHTTPClient(
        cache_dir=tmp_path,
        user_agent="test",
        min_interval_seconds=0,
        opener=lambda *_args, **_kwargs: _Response("not json"),
    )
    with pytest.raises(OpenDataError, match="invalid JSON"):
        client.get_json("https://example.test/data")
