"""Cached, rate-limited access to open research-data HTTP endpoints."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, atomic_write_text, sha256_bytes


@dataclass(frozen=True)
class HTTPArtifact:
    """One response with enough metadata to audit or reuse it."""

    url: str
    text: str
    sha256: str
    content_path: Path
    metadata_path: Path
    from_cache: bool


class OpenDataError(RuntimeError):
    """An open-data endpoint stayed unavailable or returned invalid data."""


class CachedHTTPClient:
    """Fetch immutable text artifacts with global throttling and retries."""

    def __init__(
        self,
        *,
        cache_dir: Path | str,
        user_agent: str,
        min_interval_seconds: float = 0.25,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be non-negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 1:
            raise ValueError("max_retries must be at least one")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.min_interval_seconds = float(min_interval_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self._opener = opener
        self._lock = threading.Lock()
        self._last_request = 0.0
        self.calls_made = 0
        self.cache_hits = 0

    def _paths(self, url: str, suffix: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return (
            self.cache_dir / f"{digest}{clean_suffix}",
            self.cache_dir / f"{digest}.metadata.json",
        )

    def _throttle(self) -> None:
        with self._lock:
            delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()
            self.calls_made += 1

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError, fallback: float) -> float:
        header = exc.headers.get("Retry-After") if exc.headers else None
        try:
            value = float(header) if header is not None else fallback
        except ValueError:
            value = fallback
        return min(max(value, 0.0), 30.0)

    def get_text(
        self,
        url: str,
        *,
        suffix: str = ".txt",
        accept: str = "text/plain, application/json;q=0.9, */*;q=0.1",
    ) -> HTTPArtifact:
        """Return a verified cached response or fetch and freeze it."""
        content_path, metadata_path = self._paths(url, suffix)
        if content_path.is_file() and metadata_path.is_file():
            text = content_path.read_text(encoding="utf-8")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            digest = sha256_bytes(text.encode("utf-8"))
            if metadata.get("url") != url or metadata.get("sha256") != digest:
                raise OpenDataError(
                    f"cached response provenance mismatch: {content_path}"
                )
            with self._lock:
                self.cache_hits += 1
            return HTTPArtifact(
                url=url,
                text=text,
                sha256=digest,
                content_path=content_path,
                metadata_path=metadata_path,
                from_cache=True,
            )

        request = urllib.request.Request(
            url,
            headers={"Accept": accept, "User-Agent": self.user_agent},
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    text = response.read().decode("utf-8")
                digest = sha256_bytes(text.encode("utf-8"))
                atomic_write_text(content_path, text)
                atomic_write_json(
                    metadata_path,
                    {
                        "schema_version": "1.0",
                        "url": url,
                        "sha256": digest,
                        "fetched_unix_time": time.time(),
                        "content_path": str(content_path.resolve()),
                    },
                )
                return HTTPArtifact(
                    url=url,
                    text=text,
                    sha256=digest,
                    content_path=content_path,
                    metadata_path=metadata_path,
                    from_cache=False,
                )
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise OpenDataError(
                        f"open-data request {url} returned HTTP {exc.code}: {detail}"
                    ) from exc
                last_error = exc
                wait = self._retry_after(exc, 1.5 * (2**attempt))
            except (OSError, TimeoutError, urllib.error.URLError) as exc:
                last_error = exc
                wait = min(1.5 * (2**attempt), 30.0)
            if attempt + 1 < self.max_retries:
                time.sleep(wait)
        raise OpenDataError(
            f"open-data request failed after {self.max_retries} attempts: "
            f"{url}: {last_error}"
        )

    def get_json(self, url: str) -> tuple[Any, HTTPArtifact]:
        """Fetch and validate one JSON response."""
        artifact = self.get_text(
            url,
            suffix=".json",
            accept="application/json",
        )
        try:
            return json.loads(artifact.text), artifact
        except json.JSONDecodeError as exc:
            raise OpenDataError(f"invalid JSON response from {url}: {exc}") from exc
