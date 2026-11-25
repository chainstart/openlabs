"""Shared client for free, registration-free public data sources (2026-11-25 data onboarding).

Every line tool under ``labs/<domain>/tools/*_open_data.py`` imports this module. It keeps the
container's download rules in one place:

* **Files go through the WSL download bridge** (``/workspace/.download-bridge/download-submit``).
  Nothing here opens a socket to fetch a file; :func:`submit` only shells out to the bridge.
* **Small query APIs** (a JSON/CSV answer of a few MB at most) may be read directly from Python
  through the environment's HTTP(S) proxy (the Bash hook sets 127.0.0.1:18081, Clash rules).
  :func:`query` caps the answer at ``max_bytes`` so a query can never turn into an implicit bulk
  download.
* **Large proxy downloads only off-peak.** A file >= 200 MB or a batch >= 1 GB that is known to
  need the proxy route (``route="proxy"``, or a source whose direct route is proven blocked) is
  refused outside Beijing 02:00-14:00 (:class:`OffPeakRequired`). ``route="auto"`` tries direct
  first and is not time-limited unless the source is marked ``direct_blocked``.
* **Batches resume.** :class:`Batch` keeps a JSON manifest next to the outputs; a re-run skips
  files already completed with the expected sha256/size, re-polls jobs still queued and
  re-submits failed ones (the bridge itself resumes partial files with HTTP Range).

No credentials are ever accepted: a URL with user info or a token/key/secret query parameter is
rejected (:func:`public_url`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

BRIDGE = os.environ.get("OPENLABS_DOWNLOAD_BRIDGE", "/workspace/.download-bridge/download-submit")
BEIJING = timezone(timedelta(hours=8))
OFFPEAK_START_HOUR = 2   # Beijing 02:00
OFFPEAK_END_HOUR = 14    # Beijing 14:00
LARGE_FILE_BYTES = 200 * 1024 * 1024
LARGE_BATCH_BYTES = 1024 * 1024 * 1024
DEFAULT_QUERY_MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = "openlabs-open-data/1.0 (research; low rate)"
_SECRET_KEYS = re.compile(r"token|secret|signature|credential|api.?key|access.?key|password|subscription",
                          re.IGNORECASE)


class OpenDataError(RuntimeError):
    """A request this module refuses or a download that did not complete."""


class OffPeakRequired(OpenDataError):
    """A large proxy download outside the Beijing 02:00-14:00 window."""


# --------------------------------------------------------------------------- policy helpers


def beijing_now(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(BEIJING)


def offpeak_open(now: datetime | None = None) -> bool:
    """Whether Beijing time is inside the 02:00-14:00 window for large proxy downloads."""

    hour = beijing_now(now).hour
    return OFFPEAK_START_HOUR <= hour < OFFPEAK_END_HOUR


def next_offpeak_start(now: datetime | None = None) -> datetime:
    moment = beijing_now(now)
    start = moment.replace(hour=OFFPEAK_START_HOUR, minute=0, second=0, microsecond=0)
    if moment >= start:
        start += timedelta(days=1)
    return start


def is_large(file_bytes: int | None = None, batch_bytes: int | None = None) -> bool:
    return bool((file_bytes or 0) >= LARGE_FILE_BYTES or (batch_bytes or 0) >= LARGE_BATCH_BYTES)


def proxy_bound(route: str, direct_blocked: bool) -> bool:
    """Whether a download will (or is known to) use the proxy channel."""

    return route == "proxy" or (route == "auto" and direct_blocked)


def check_window(*, route: str, direct_blocked: bool = False, file_bytes: int | None = None,
                 batch_bytes: int | None = None, large: bool = False,
                 now: datetime | None = None) -> None:
    """Raise :class:`OffPeakRequired` for a large proxy-bound download outside the window."""

    if not proxy_bound(route, direct_blocked):
        return
    if not (large or is_large(file_bytes, batch_bytes)):
        return
    if offpeak_open(now):
        return
    raise OffPeakRequired(
        "large download over the proxy channel is only allowed Beijing 02:00-14:00; next window "
        f"opens {next_offpeak_start(now).isoformat()} (do not split files to get around this)")


def public_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise OpenDataError(f"plain public HTTP(S) URL required: {url}")
    if parsed.username or parsed.password:
        raise OpenDataError("URLs with credentials are refused")
    for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if _SECRET_KEYS.search(key):
            raise OpenDataError(f"credential-bearing query parameter refused: {key}")
    return url


def s3_https(uri: str) -> str:
    """``s3://bucket/key`` -> ``https://bucket.s3.amazonaws.com/key`` (the bridge takes HTTP(S) only)."""

    if not uri.startswith("s3://"):
        return uri
    bucket, _, key = uri[len("s3://"):].partition("/")
    return f"https://{bucket}.s3.amazonaws.com/{urllib.parse.quote(key)}"


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- small queries


def query(url: str, params: Mapping[str, Any] | None = None, *, timeout: float = 120,
          max_bytes: int = DEFAULT_QUERY_MAX_BYTES, data: bytes | None = None,
          headers: Mapping[str, str] | None = None) -> bytes:
    """A small API answer (<= ``max_bytes``) read through the environment proxy.

    For answers that are kept as data files use :func:`submit` (the bridge) instead.
    """

    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    public_url(url)
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT,
                                                              **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise OpenDataError(f"answer of {length} bytes exceeds the query cap {max_bytes}; "
                                "use the bridge (submit) for files")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise OpenDataError(f"answer exceeds the query cap {max_bytes} bytes; use the bridge")
    return body


def query_json(url: str, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
    return json.loads(query(url, params, **kwargs).decode("utf-8"))


def looks_like_html(body: bytes | str) -> bool:
    """Maintenance/denial pages often come back with HTTP 200 (Gaia archive 2026-11-25)."""

    head = body[:512].lstrip().lower() if isinstance(body, bytes) else body[:512].lstrip().lower().encode()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


# --------------------------------------------------------------------------- bridge


def _parse_lines(text: str) -> list[dict[str, Any]]:
    records = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


def submit(url: str, output: str | Path, *, sha256: str | None = None, route: str = "auto",
           expected_bytes: int | None = None, task_bytes: int | None = None, large: bool = False,
           direct_blocked: bool = False, wait: bool = True, timeout: int = 120,
           runner: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Submit one download to the bridge; returns the last status record it printed.

    ``state`` is ``completed`` only when the bridge says so. A wait timeout leaves the job
    queued/running (``state`` queued/running, ``wait_timed_out`` true): poll :func:`status`.
    """

    public_url(url)
    out = Path(output)
    if not str(out).startswith("/workspace/") or "/.download-bridge/" in str(out):
        raise OpenDataError("bridge outputs must be under /workspace/ and outside .download-bridge")
    if route not in {"auto", "direct", "proxy"}:
        raise OpenDataError(f"unknown route {route}")
    check_window(route=route, direct_blocked=direct_blocked, file_bytes=expected_bytes,
                 batch_bytes=task_bytes, large=large, now=now)
    out.parent.mkdir(parents=True, exist_ok=True)
    command = [BRIDGE, "--url", url, "--output", str(out), "--route", route]
    if sha256:
        command += ["--sha256", sha256.lower()]
    if expected_bytes:
        command += ["--expected-bytes", str(int(expected_bytes))]
    if task_bytes:
        command += ["--task-bytes", str(int(task_bytes))]
    if large or is_large(expected_bytes, task_bytes):
        command.append("--large")
    if wait:
        command += ["--wait", "--timeout", str(int(timeout))]
    run = runner or subprocess.run
    proc = run(command, capture_output=True, text=True, timeout=(timeout + 60) if wait else 120)
    records = _parse_lines(proc.stdout or "")
    record = dict(records[-1]) if records else {}
    if records and "id" not in record:
        record["id"] = next((r.get("id") for r in records if r.get("id")), None)
    record.setdefault("state", "unknown")
    record["returncode"] = proc.returncode
    if proc.returncode != 0 and "timed out" in (proc.stdout or "") + (proc.stderr or ""):
        record["wait_timed_out"] = True
    if proc.returncode != 0 and not records:
        record["error"] = ((proc.stderr or "") + (proc.stdout or ""))[-800:]
    return record


def status(job_id: str, *, runner: Any = None) -> dict[str, Any]:
    run = runner or subprocess.run
    proc = run([BRIDGE, "--status", job_id], capture_output=True, text=True, timeout=120)
    records = _parse_lines(proc.stdout or "")
    return records[-1] if records else {"id": job_id, "state": "unknown",
                                        "error": (proc.stderr or "")[-400:]}


def route_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """The channel facts a source-selection record keeps."""

    return {key: record.get(key) for key in ("id", "state", "route", "route_policy",
                                             "routes_attempted", "fallback_reason", "bytes")
            if record.get(key) is not None}


# --------------------------------------------------------------------------- batches


@dataclass
class Item:
    url: str
    output: str
    sha256: str | None = None
    expected_bytes: int | None = None
    estimated_bytes: int | None = None   # honest estimate when the size is not verified
    job_id: str | None = None
    state: str = "pending"
    route: str | None = None
    routes_attempted: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    note: str | None = None

    def done_on_disk(self) -> bool:
        path = Path(self.output)
        if not path.is_file():
            return False
        if self.expected_bytes and path.stat().st_size != int(self.expected_bytes):
            return False
        if self.sha256:
            return sha256_file(path) == self.sha256.lower()
        return self.state == "completed"


class Batch:
    """A resumable multi-file download: a JSON manifest of :class:`Item`s.

    ``run(limit=N)`` submits at most N new items per call (default all), so a large dataset can be
    fetched in slices; items already done on disk are never re-submitted.
    """

    def __init__(self, manifest: str | Path, *, route: str = "auto", direct_blocked: bool = False):
        self.manifest = Path(manifest)
        self.route = route
        self.direct_blocked = direct_blocked
        self.items: list[Item] = []
        if self.manifest.is_file():
            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
            self.items = [Item(**item) for item in payload.get("items", [])]

    def add(self, url: str, output: str, *, sha256: str | None = None,
            expected_bytes: int | None = None, estimated_bytes: int | None = None) -> Item:
        for item in self.items:
            if item.output == output:
                return item
        item = Item(url=url, output=output, sha256=sha256, expected_bytes=expected_bytes,
                    estimated_bytes=estimated_bytes)
        self.items.append(item)
        return item

    def total_bytes(self) -> int:
        """Verified sizes, else estimates: the bridge's --task-bytes (a size-less job whose direct
        route fails is otherwise parked as a large proxy download until 02:00 Beijing)."""

        return sum(int(item.expected_bytes or item.estimated_bytes or 0) for item in self.items)

    def save(self) -> None:
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "openlabs.open_data.batch.v1", "updated_at": utc_now(),
                   "route": self.route, "direct_blocked": self.direct_blocked,
                   "total_expected_bytes": self.total_bytes(),
                   "items": [item.__dict__ for item in self.items]}
        tmp = self.manifest.with_suffix(self.manifest.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.manifest)

    def run(self, *, limit: int | None = None, wait: bool = False, timeout: int = 120,
            runner: Any = None, now: datetime | None = None) -> dict[str, int]:
        check_window(route=self.route, direct_blocked=self.direct_blocked,
                     batch_bytes=self.total_bytes(), now=now)
        submitted = 0
        for item in self.items:
            if item.state == "completed" and item.done_on_disk():
                continue
            if item.done_on_disk():
                item.state = "completed"
                continue
            if item.job_id and item.state in {"queued", "running", "submitted"}:
                record = status(item.job_id, runner=runner)
                self._apply(item, record)
                if item.state in {"queued", "running", "completed"}:
                    continue
            if limit is not None and submitted >= limit:
                continue
            record = submit(item.url, item.output, sha256=item.sha256, route=self.route,
                            expected_bytes=item.expected_bytes, task_bytes=self.total_bytes() or None,
                            direct_blocked=self.direct_blocked, wait=wait, timeout=timeout,
                            runner=runner, now=now)
            self._apply(item, record)
            submitted += 1
            self.save()
        self.save()
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.state] = counts.get(item.state, 0) + 1
        counts["submitted_now"] = submitted
        return counts

    @staticmethod
    def _apply(item: Item, record: Mapping[str, Any]) -> None:
        item.job_id = record.get("id") or item.job_id
        item.state = str(record.get("state") or item.state)
        item.route = record.get("route") or item.route
        item.routes_attempted = list(record.get("routes_attempted") or item.routes_attempted)
        item.fallback_reason = record.get("fallback_reason") or item.fallback_reason


# --------------------------------------------------------------------------- provenance


def write_selection(path: str | Path, *, source_id: str, original: str,
                    domestic_candidates: Iterable[Mapping[str, Any]], chosen: str,
                    route: Mapping[str, Any] | None = None, notes: str = "") -> dict[str, Any]:
    """Write the per-source selection record the download rules ask for."""

    record = {
        "schema": "openlabs.open_data.source_selection.v1",
        "source_id": source_id,
        "recorded_at": utc_now(),
        "original_source": original,
        "domestic_candidates": list(domestic_candidates),
        "chosen_source": chosen,
        "route": dict(route or {}),
        "notes": notes,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    return record


def wait_for(job_id: str, *, timeout: float = 600, poll: float = 10, runner: Any = None,
             sleeper: Any = time.sleep) -> dict[str, Any]:
    """Poll a bridge job until it leaves queued/running or ``timeout`` seconds pass."""

    deadline = time.monotonic() + timeout
    record = status(job_id, runner=runner)
    while record.get("state") in {"queued", "running"} and time.monotonic() < deadline:
        sleeper(poll)
        record = status(job_id, runner=runner)
    return record
