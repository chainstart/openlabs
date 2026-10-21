"""Bounded public HTTPS downloads with file-level reuse and provenance records.

Run as `python -m tools.dataset_intake` from the lab directory, under the guard.
Retries resume within an invocation only when HTTP validators make it safe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.client import IncompleteRead
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from tools.common import CODE_ROOT, LAB_ROOT, atomic_json, identifier, read_json, sha256


def source_record(source_id: str) -> dict:
    registry = read_json(LAB_ROOT / "registries/data_sources.json")
    for source in registry["sources"]:
        if source["source_id"] == source_id:
            return source
    raise ValueError(f"unregistered source: {source_id}")


def public_url(url: str, hosts: list[str] | None = None, *, allow_signed: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("public HTTPS URL without credentials required")
    if parsed.port not in {None, 443} or parsed.fragment:
        raise ValueError("standard HTTPS port and no fragment required")
    if hosts is not None and parsed.hostname not in hosts:
        raise ValueError(f"host is not registered: {parsed.hostname}")
    for key, _ in parse_qsl(parsed.query):
        if not allow_signed and re.search(
            r"token|secret|signature|credential|api.?key|access.?key|password",
            key,
            re.I,
        ):
            raise ValueError("credential-bearing URLs must not enter public provenance")
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts: list[str]):
        self.hosts = hosts
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Public release endpoints may issue temporary signed object-store redirects.
        # They stay in memory only; provenance records the stable original public URL.
        public_url(newurl, self.hosts, allow_signed=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_validator(headers) -> str | None:
    etag = headers.get("ETag")
    return etag if etag and not etag.startswith("W/") else headers.get("Last-Modified")


def validate_manifest(manifest: dict, *, verify_payload: bool = False) -> list[str]:
    errors = []
    if manifest.get("schema_version") != "openlabs.biomed_dataset.v1":
        errors.append("unknown dataset manifest schema")
    for field in (
        "dataset_id",
        "source_id",
        "release_or_accession",
        "independent_unit",
        "terms_url",
        "reuse_basis",
        "citation",
        "retrieved_at_utc",
        "staging_root",
    ):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            errors.append(f"{field} required")
    if manifest.get("access_scope") != "public" or manifest.get("raw_immutable") is not True:
        errors.append("immutable public data required")
    upstream = manifest.get("upstream_study_ids")
    if (
        not isinstance(upstream, list)
        or not upstream
        or any(not isinstance(item, str) or not item.strip() for item in upstream)
    ):
        errors.append("upstream_study_ids required; explicitly record unknown if unresolved")
    try:
        source = source_record(manifest.get("source_id", ""))
        public_url(manifest.get("source_url", ""), source["allowed_hosts"])
        public_url(manifest.get("final_url", ""), source["allowed_hosts"])
        public_url(manifest.get("terms_url", ""))
        datetime.fromisoformat(manifest.get("retrieved_at_utc", "").replace("Z", "+00:00"))
        uri = urlparse(manifest.get("artifact_uri", ""))
        if uri.scheme != "file" or uri.netloc or not Path(unquote(uri.path)).is_absolute():
            raise ValueError("local absolute file URI required")
        staging = Path(manifest.get("staging_root", "")).resolve()
        payload = Path(unquote(uri.path)).resolve()
        if not payload.is_relative_to(staging):
            raise ValueError("payload escapes declared staging root")
        if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("sha256", ""))):
            raise ValueError("payload SHA-256 required")
        size = manifest.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError("positive payload byte count required")
        if verify_payload and (
            not payload.is_file()
            or payload.stat().st_size != size
            or sha256(payload) != manifest["sha256"]
        ):
            raise ValueError("payload missing or size/SHA-256 mismatch")
    except (ValueError, TypeError, OSError) as exc:
        errors.append(str(exc))
    return errors


def download(
    *,
    source_id: str,
    url: str,
    staging_root: Path,
    dataset_id: str,
    release_or_accession: str,
    independent_unit: str,
    terms_url: str,
    reuse_basis: str,
    citation: str,
    upstream_study_ids: list[str],
    filename: str = "data.bin",
    expected_sha256: str | None = None,
    max_bytes: int = 64 * 1024**2,
    retries: int = 2,
) -> dict:
    source = source_record(source_id)
    public_url(url, source["allowed_hosts"])
    public_url(terms_url)
    identifier(dataset_id)
    identifier(filename)
    if filename in {"manifest.json"}:
        raise ValueError("reserved payload filename")
    for value in (release_or_accession, independent_unit, reuse_basis, citation):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("release, sample unit, reuse basis and citation are required")
    if not upstream_study_ids or any(not item.strip() for item in upstream_study_ids):
        raise ValueError("record upstream study identifiers or explicit unknown")
    if max_bytes < 1 or retries not in range(4):
        raise ValueError("positive byte ceiling and 0..3 retries required")
    if expected_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("invalid expected SHA-256")
    staging_root = staging_root.resolve()
    if staging_root.is_relative_to(CODE_ROOT) or "openlabs-data" in staging_root.parts:
        raise ValueError("payloads belong in external artifact staging, not code/data Git")
    if {"objects", "result-bundles"}.intersection(staging_root.parts):
        raise ValueError("do not write directly into published artifact stores")
    staging_root.mkdir(parents=True, exist_ok=True)
    destination = staging_root / dataset_id
    destination.mkdir(exist_ok=False)  # Never replace an earlier dataset or provenance record.
    output = destination / filename
    descriptor, temporary = tempfile.mkstemp(prefix=".download-", dir=destination)
    os.close(descriptor)
    partial = Path(temporary)
    opener = urllib.request.build_opener(PublicRedirect(source["allowed_hosts"]))
    digest = hashlib.sha256()
    size = 0
    validator = None
    headers = None
    try:
        for attempt in range(retries + 1):
            request_headers = {
                "User-Agent": "OpenLabs-biomed/0.1 public-data-intake",
                "Accept-Encoding": "identity",
            }
            if size and validator:
                request_headers.update({"Range": f"bytes={size}-", "If-Range": validator})
            elif size:
                partial.write_bytes(b"")
                digest = hashlib.sha256()
                size = 0
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with opener.open(request, timeout=30) as response:
                    public_url(response.url, source["allowed_hosts"], allow_signed=True)
                    headers = response.headers
                    if response.status == 206:
                        match = re.fullmatch(
                            r"bytes (\d+)-(\d+)/(\d+)", headers.get("Content-Range", "")
                        )
                        if not match or int(match[1]) != size:
                            raise ValueError("invalid or mismatched HTTP Content-Range")
                        if validator != http_validator(headers):
                            raise ValueError("remote dataset changed during download")
                        if int(match[3]) > max_bytes:
                            raise ValueError("remote dataset exceeds byte ceiling")
                    elif response.status == 200:
                        if size:
                            partial.write_bytes(b"")
                            digest = hashlib.sha256()
                            size = 0
                    else:
                        raise ValueError(f"unexpected HTTP status: {response.status}")
                    validator = http_validator(headers)
                    if "text/html" in headers.get("Content-Type", "").lower():
                        raise ValueError("received HTML, possibly a login or verification page")
                    expected = headers.get("Content-Length")
                    if expected is not None and size + int(expected) > max_bytes:
                        raise ValueError("remote dataset exceeds byte ceiling")
                    received = 0
                    with partial.open("ab") as handle:
                        while chunk := response.read(1024 * 1024):
                            size += len(chunk)
                            received += len(chunk)
                            if size > max_bytes:
                                raise ValueError("download exceeds byte ceiling")
                            digest.update(chunk)
                            handle.write(chunk)
                    if expected is not None and received != int(expected):
                        raise EOFError("incomplete HTTP body")
                    if response.status == 206 and size != int(match[3]):
                        raise EOFError("incomplete ranged download")
                    final_url = response.url
                    try:
                        public_url(final_url, source["allowed_hosts"])
                        redacted = False
                    except ValueError:
                        final_url = urlparse(final_url)._replace(query="").geturl()
                        redacted = True
                break
            except (OSError, EOFError, IncompleteRead) as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in {
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    raise
                if attempt == retries:
                    raise
                time.sleep(min(2 ** (attempt + 1), 8))
        actual = digest.hexdigest()
        if size == 0 or (expected_sha256 is not None and actual != expected_sha256):
            raise ValueError("empty payload or SHA-256 mismatch")
        os.link(partial, output)
        manifest = {
            "schema_version": "openlabs.biomed_dataset.v1",
            "dataset_id": dataset_id,
            "source_id": source_id,
            "source_url": url,
            "final_url": final_url,
            "release_or_accession": release_or_accession,
            "final_url_query_redacted": redacted,
            "independent_unit": independent_unit,
            "terms_url": terms_url,
            "reuse_basis": reuse_basis,
            "citation": citation,
            "upstream_study_ids": upstream_study_ids,
            "access_scope": "public",
            "retrieved_at_utc": datetime.now(UTC).isoformat(),
            "artifact_uri": output.as_uri(),
            "sha256": actual,
            "bytes": size,
            "staging_root": str(staging_root),
            "raw_immutable": True,
            "http": {
                "etag": headers.get("ETag"),
                "last_modified": headers.get("Last-Modified"),
                "content_type": headers.get("Content-Type"),
            },
        }
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError("; ".join(errors))
        atomic_json(destination / "manifest.json", manifest)
        return manifest
    finally:
        partial.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-id",
        "url",
        "dataset-id",
        "release-or-accession",
        "independent-unit",
        "terms-url",
        "reuse-basis",
        "citation",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--upstream-study-id", action="append", required=True)
    parser.add_argument("--staging-root", required=True, type=Path)
    parser.add_argument("--filename", default="data.bin")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024**2)
    args = vars(parser.parse_args())
    args["upstream_study_ids"] = args.pop("upstream_study_id")
    try:
        print(json.dumps({"valid": True, "manifest": download(**args)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
