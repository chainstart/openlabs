#!/usr/bin/env python3
"""Download a public physics dataset into artifacts and emit a provenance manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

SCHEMA = "openlabs.physics_dataset.v1"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
DEFAULT_MAX_BYTES = 8 * 1024**3


def _identifier(value: str, field: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must match {IDENTIFIER.pattern}")
    return value


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def download(
    *,
    url: str,
    artifacts_root: Path,
    campaign_id: str,
    dataset_id: str,
    provider: str,
    license_or_terms: str,
    citation: str,
    filename: str | None,
    expected_sha256: str | None,
    max_bytes: int,
) -> tuple[Path, dict[str, object]]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must use http or https")
    campaign_id = _identifier(campaign_id, "campaign_id")
    dataset_id = _identifier(dataset_id, "dataset_id")
    inferred = Path(parsed.path).name or "dataset.bin"
    filename = _identifier(filename or inferred, "filename")
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    if expected_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected_sha256 must be lowercase SHA-256")

    destination = artifacts_root.resolve() / "experiments" / campaign_id / "raw" / dataset_id
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / filename
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing raw artifact: {output}")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.part")
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(url, headers={"User-Agent": "OpenLabs/physics-dataset-intake"})
    try:
        response = urllib.request.urlopen(request, timeout=60)
        with response, temporary.open("xb") as handle:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"download exceeds max_bytes={max_bytes}")
                digest.update(chunk)
                handle.write(chunk)
            headers = response.headers
        actual_sha256 = digest.hexdigest()
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise ValueError("downloaded SHA-256 does not match expected_sha256")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    manifest: dict[str, object] = {
        "schema_version": SCHEMA,
        "dataset_id": dataset_id,
        "provider": provider,
        "source_url": url,
        "acquired_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "license_or_terms": license_or_terms,
        "citation": citation,
        "access_scope": "public",
        "artifact_uri": output.as_uri(),
        "sha256": actual_sha256,
        "bytes": size,
        "raw_immutable": True,
        "http": {
            "etag": headers.get("ETag"),
            "last_modified": headers.get("Last-Modified"),
            "content_type": headers.get("Content-Type"),
        },
    }
    return output, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--license-or-terms", required=True)
    parser.add_argument("--citation", required=True)
    parser.add_argument("--filename")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    output, manifest = download(
        url=args.url,
        artifacts_root=args.artifacts_root,
        campaign_id=args.campaign_id,
        dataset_id=args.dataset_id,
        provider=args.provider,
        license_or_terms=args.license_or_terms,
        citation=args.citation,
        filename=args.filename,
        expected_sha256=args.expected_sha256,
        max_bytes=args.max_bytes,
    )
    _atomic_json(args.manifest.resolve(), manifest)
    print(json.dumps({"artifact": str(output), "manifest": str(args.manifest.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
