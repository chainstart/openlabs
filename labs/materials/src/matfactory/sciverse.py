"""Sciverse Open Platform client.

Encodes the request shapes verified against the live API on 2026-08-06. The
published SDK sugar (``year_from``, ``filters_advanced``, ``size``) is rejected
by the raw endpoints with ``extra_forbidden`` -- only the field names used here
are accepted.

Endpoints (base https://api.sciverse.space):
    GET  /meta-catalog          field schema for a collection
    POST /meta-search           structured metadata search (BM25 + filters)
    POST /agentic-search        semantic/RAG search over passages
    GET  /content               byte-range slice of a parsed document
    GET  /resource              figure/table image bytes

Every response carries provenance we keep: ``doc_id`` (content hash of the
parsed artifact), ``page_no``, and ``offset``. A (doi, doc_id, offset) triple
re-fetches the exact source text, which is what makes extracted values
auditable.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .provenance import atomic_write_json

BASE_URL = "https://api.sciverse.space"

# Server-side ceilings, verified by probing.
MAX_PAGE_SIZE = 50
MAX_CONTENT_LIMIT = 16384
MAX_TOP_K = 100

# /meta-search reports total_count saturated at this value; it is a ceiling,
# not a real count, so it must never be used for coverage statistics.
TOTAL_COUNT_CEILING = 10000


def _retry_after_seconds(detail: str, *, default: float) -> float:
    """Seconds to wait, read from a 429 body's ``details.retry_after``."""
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return default
    details = payload.get("details")
    if isinstance(details, dict):
        value = details.get("retry_after")
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
    return default


class SciverseError(RuntimeError):
    """Raised when the API rejects a request or stays unavailable."""


class SciverseFetchUnavailable(SciverseError):
    """The document is indexed but its fulltext cannot be served.

    Distinguished from a generic failure so callers can skip the document and
    record it, instead of retrying something that will never succeed.
    """


class SciverseDocumentTruncated(SciverseError):
    """A configured safety limit or invalid cursor prevented a full download."""


@dataclass
class Paper:
    """A metadata record. ``doc_id`` is present only when full text exists."""

    unique_id: str
    title: str
    doi: str | None
    year: int | None
    doc_id: str | None
    venue: str | None
    abstract: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def has_fulltext(self) -> bool:
        return bool(self.doc_id)

    @classmethod
    def from_hit(cls, hit: dict[str, Any]) -> "Paper":
        year = hit.get("publication_published_year")
        # The API returns years as floats (2021.0).
        if isinstance(year, float):
            year = int(year)
        return cls(
            unique_id=hit.get("unique_id") or "",
            title=(hit.get("title") or "").strip(),
            doi=hit.get("doi") or None,
            year=year,
            doc_id=hit.get("doc_id") or None,
            venue=hit.get("publication_venue_name_unified") or None,
            abstract=hit.get("abstract") or None,
            raw=hit,
        )


@dataclass
class Passage:
    """A semantic-search hit: a text chunk with byte-level provenance."""

    doc_id: str
    chunk_id: str
    text: str
    offset: int
    page_no: int | None
    score: float
    title: str
    year: int | None
    doi: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_hit(cls, hit: dict[str, Any]) -> "Passage":
        year = hit.get("publication_published_year")
        if isinstance(year, float):
            year = int(year)
        return cls(
            doc_id=hit.get("doc_id") or "",
            chunk_id=hit.get("chunk_id") or "",
            text=hit.get("chunk") or "",
            offset=int(hit.get("offset") or 0),
            page_no=hit.get("page_no"),
            score=float(hit.get("score") or 0.0),
            title=(hit.get("title") or "").strip(),
            year=year,
            doi=hit.get("doi") or None,
            raw=hit,
        )


class SciverseClient:
    """Thin, cached, rate-limited client.

    Responses are cached on disk keyed by (method, path, body) so that a rerun
    of an extraction pass costs no API calls and stays byte-identical. The
    cache doubles as the audit trail the competition asks for: every value we
    report can be traced to the exact stored response that produced it.
    """

    def __init__(
        self,
        token: str | None = None,
        cache_dir: Path | str = "cache/sciverse",
        # The /content endpoint allows 30 calls per minute per account, so
        # 2.1s between calls keeps a long harvest just inside the quota
        # instead of spending it in the first twenty seconds.
        min_interval: float = 2.1,
        max_retries: int = 4,
        timeout: float = 90.0,
    ) -> None:
        self.token = token or os.environ.get("SCIVERSE_API_TOKEN") or ""
        if not self.token:
            raise SciverseError(
                "No API token. Set SCIVERSE_API_TOKEN "
                "(see ~/.config/goai/env) or pass token=."
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_call = 0.0
        # An API call means an attempted HTTP request, including errors and
        # retries. Counting only 2xx responses made quota reports dangerously
        # optimistic during a failure-heavy harvest.
        self.calls_made = 0
        self.successful_calls = 0
        self.rate_limit_hits = 0
        self.cache_hits = 0

    # ---------------------------------------------------------------- plumbing

    def _cache_path(self, method: str, path: str, payload: Any) -> Path:
        key = json.dumps(
            {"m": method, "p": path, "b": payload}, sort_keys=True, ensure_ascii=False
        )
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        return self.cache_dir / f"{path.strip('/').replace('/', '_')}_{digest}.json"

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        cache_key = payload if method == "POST" else params
        cache_file = self._cache_path(method, path, cache_key)
        if use_cache and cache_file.exists():
            self.cache_hits += 1
            return json.loads(cache_file.read_text(encoding="utf-8"))

        url = f"{BASE_URL}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            self.calls_made += 1
            request = urllib.request.Request(
                url, data=data, headers=headers, method=method
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode())
                self.successful_calls += 1
                if body.get("code") == "INVALID_REQUEST":
                    # A malformed request never succeeds on retry.
                    raise SciverseError(
                        f"{path} rejected the request: "
                        f"{json.dumps(body.get('details'), ensure_ascii=False)}"
                    )
                if use_cache:
                    atomic_write_json(cache_file, body, indent=None)
                return body
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:400]
                # This stable missing-content condition must be classified
                # before generic 404 handling; otherwise it is unreachable and
                # callers cannot record the document as permanently unavailable.
                if exc.code == 404 and "CONTENT_NOT_FOUND" in detail:
                    raise SciverseFetchUnavailable(
                        f"{path} has no stored fulltext: {detail}"
                    ) from exc
                if exc.code in (400, 401, 403, 404):
                    raise SciverseError(f"{path} HTTP {exc.code}: {detail}") from exc
                if exc.code == 429:
                    # The API states its own cooldown; obeying it is both
                    # faster and politer than exponential backoff, which
                    # otherwise sleeps too little and burns the next window too.
                    wait = _retry_after_seconds(detail, default=20.0)
                    last_error = SciverseError(f"{path} rate limited: {detail}")
                    self.rate_limit_hits += 1
                    time.sleep(wait + 1.0)
                    continue
                if exc.code == 502 and "FETCH_FAILED" in detail:
                    # The index advertises has_fulltext for documents whose text
                    # the upstream store cannot actually serve. This is stable,
                    # not transient: the same doc_id returns FETCH_FAILED on
                    # every retry. Retrying costs four calls and ~22s of backoff
                    # per document, and at the observed ~80% miss rate that is
                    # most of the harvest budget, so give up immediately.
                    raise SciverseFetchUnavailable(
                        f"{path} has no retrievable fulltext: {detail}"
                    ) from exc
                last_error = SciverseError(f"{path} HTTP {exc.code}: {detail}")
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
                # Large search responses get truncated mid-body often enough
                # that an uncaught IncompleteRead will end a long harvest.
                http.client.IncompleteRead,
                http.client.HTTPException,
                ConnectionError,
                OSError,
            ) as exc:
                last_error = exc
            time.sleep(1.5 * (2**attempt))

        raise SciverseError(f"{path} failed after {self.max_retries} tries: {last_error}")

    # ------------------------------------------------------------------- tools

    def catalog(
        self, collection: str = "papers", *, sample_values: bool = False
    ) -> dict[str, Any]:
        """Field schema for a collection. Call once to learn filterable names."""
        return self._request(
            "GET",
            "/meta-catalog",
            params={
                "collection": collection,
                "include_sample_values": str(sample_values).lower(),
            },
        )

    def search_papers(
        self,
        query: str = "",
        *,
        page: int = 1,
        page_size: int = MAX_PAGE_SIZE,
        year_min: int | None = None,
        year_max: int | None = None,
        filters: list[dict[str, Any]] | None = None,
        collection: str = "papers",
        freshness_boost: str | None = None,
    ) -> tuple[list[Paper], dict[str, Any]]:
        """Structured metadata search.

        ``year_min`` / ``year_max`` are compiled into the ``filters`` array the
        API actually accepts -- the documented ``year_from`` / ``year_to`` keys
        are SDK-only and are refused by this endpoint.
        """
        combined: list[dict[str, Any]] = list(filters or [])
        if year_min is not None:
            combined.append(
                {
                    "field": "publication_published_year",
                    "operator": "FILTER_OP_GTE",
                    "value": year_min,
                }
            )
        if year_max is not None:
            combined.append(
                {
                    "field": "publication_published_year",
                    "operator": "FILTER_OP_LTE",
                    "value": year_max,
                }
            )

        payload: dict[str, Any] = {
            "collection": collection,
            "page": page,
            "page_size": min(page_size, MAX_PAGE_SIZE),
        }
        if query:
            payload["query"] = query
        if combined:
            payload["filters"] = combined
        if freshness_boost:
            payload["freshness_boost"] = freshness_boost

        body = self._request("POST", "/meta-search", payload=payload)
        papers = [Paper.from_hit(hit) for hit in body.get("results") or []]
        meta = {
            "total_count": body.get("total_count"),
            "total_count_is_ceiling": body.get("total_count") == TOTAL_COUNT_CEILING,
            "page": body.get("page"),
            "page_size": body.get("page_size"),
            "total_pages": body.get("total_pages"),
            "search_time_ms": body.get("search_time_ms"),
        }
        return papers, meta

    def iter_papers(
        self,
        query: str = "",
        *,
        limit: int = 200,
        page_size: int = MAX_PAGE_SIZE,
        fulltext_only: bool = False,
        **kwargs: Any,
    ) -> Iterator[Paper]:
        """Page through results, de-duplicating as it goes.

        Dedup is not optional: a single query routinely returns a paper
        alongside its own supplementary-material record (DOI suffixed
        ``.s001``) and near-identical preprint/journal pairs. Supplements are
        dropped rather than kept as separate papers -- their tables belong to
        the parent article, and counting both would double-count samples.
        """
        seen_ids: set[str] = set()
        seen_dois: set[str] = set()
        seen_titles: set[str] = set()
        yielded = 0
        page = 1
        while yielded < limit:
            papers, meta = self.search_papers(
                query, page=page, page_size=page_size, **kwargs
            )
            if not papers:
                return
            for paper in papers:
                if fulltext_only and not paper.has_fulltext:
                    continue
                identity = paper.doc_id or paper.unique_id or paper.doi or ""
                if identity and identity in seen_ids:
                    continue
                doi_key = base_doi(paper.doi)
                if doi_key and doi_key in seen_dois:
                    continue
                title_key = _title_key(paper.title)
                if title_key and title_key in seen_titles:
                    continue
                if identity:
                    seen_ids.add(identity)
                if doi_key:
                    seen_dois.add(doi_key)
                if title_key:
                    seen_titles.add(title_key)
                yield paper
                yielded += 1
                if yielded >= limit:
                    return
            if meta.get("total_pages") and page >= int(meta["total_pages"]):
                return
            page += 1

    def semantic_search(
        self,
        query: str,
        *,
        top_k: int = 20,
        mode: str = "balanced",
        source_types: list[str] | None = None,
    ) -> list[Passage]:
        """Natural-language passage retrieval.

        ``balanced`` is capped near 50 hits server-side and returns at most
        ~3 chunks per paper, so breadth needs several distinct queries rather
        than one large ``top_k``.
        """
        payload: dict[str, Any] = {
            "query": query,
            "top_k": min(top_k, MAX_TOP_K),
            "mode": mode,
        }
        if source_types:
            payload["source_types"] = source_types
        body = self._request("POST", "/agentic-search", payload=payload)
        return [Passage.from_hit(hit) for hit in body.get("hits") or []]

    def read_content(
        self, doc_id: str, *, offset: int = 0, limit: int = MAX_CONTENT_LIMIT
    ) -> dict[str, Any]:
        """One byte-range slice of a parsed document."""
        return self._request(
            "GET",
            "/content",
            params={
                "doc_id": doc_id,
                "offset": offset,
                "limit": min(limit, MAX_CONTENT_LIMIT),
            },
        )

    def read_full_document(self, doc_id: str, *, max_chars: int = 2_000_000) -> str:
        """Concatenate every slice into the whole parsed document.

        Follows the server's ``next_offset``/``more`` cursor. Offsets are byte
        positions, so they are not interchangeable with string indices into
        the returned text.
        """
        parts: list[str] = []
        offset = 0
        total = 0
        while total < max_chars:
            body = self.read_content(doc_id, offset=offset, limit=MAX_CONTENT_LIMIT)
            text = body.get("text") or ""
            if not text:
                if body.get("more"):
                    raise SciverseDocumentTruncated(
                        f"{doc_id}: empty content page at byte offset {offset}"
                    )
                break
            parts.append(text)
            total += len(text)
            if not body.get("more"):
                break
            next_offset = body.get("next_offset")
            if next_offset is None or next_offset <= offset:
                raise SciverseDocumentTruncated(
                    f"{doc_id}: invalid next_offset {next_offset!r} after {offset}"
                )
            offset = int(next_offset)
        if body.get("more"):
            raise SciverseDocumentTruncated(
                f"{doc_id}: document exceeds max_chars={max_chars}; "
                "partial text was not returned"
            )
        return "".join(parts)

    def stats(self) -> dict[str, int]:
        return {
            "api_calls": self.calls_made,
            "successful_calls": self.successful_calls,
            "cache_hits": self.cache_hits,
            "rate_limit_hits": self.rate_limit_hits,
        }


_SUPPLEMENT_SUFFIX = re.compile(r"\.s\d{2,3}$", re.I)


def base_doi(doi: str | None) -> str:
    """Strip a supplementary-material suffix to get the parent article DOI.

    Publishers register supplements as their own DOIs (``10.1021/x.s001``),
    and Sciverse indexes them as separate papers with their own ``doc_id``.
    """
    if not doi:
        return ""
    return _SUPPLEMENT_SUFFIX.sub("", doi.strip().lower())


def _title_key(title: str) -> str:
    """Normalised title for near-duplicate detection.

    Titles arrive with literal two-character ``\\n`` sequences from the
    upstream parse, which would otherwise leave an "n" fused onto the next
    word and defeat exact-title matching.
    """
    text = title.lower().replace("\\n", " ").replace("\\t", " ")
    lowered = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(lowered.split())[:120]
