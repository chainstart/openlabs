"""Rebuild the fact table from the parsed-document cache, without the API.

Extraction rules change far more often than the corpus does, so the full text
of every fetched paper is kept on disk. This lets a parser fix be re-applied to
everything already downloaded in seconds, and makes the fact table reproducible
from the cache alone.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .provenance import atomic_write_json, atomic_write_text, file_manifest, fingerprint, sha256_file
from .tables import ExtractionStats, extract_records, merge_by_sample


def load_index(*paths: Path) -> dict[str, dict]:
    """Map doc_id -> bibliographic metadata.

    The parsed cache is keyed by doc_id and holds no metadata of its own. The
    manifest written alongside it covers every fetched paper; an existing fact
    file is accepted as a fallback for corpora harvested before the manifest
    existed. Earlier sources win, so the manifest takes precedence.
    """
    index: dict[str, dict] = {}
    for path in paths:
        if not path or not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            doc_id = record.get("doc_id")
            if not doc_id:
                continue
            current = index.setdefault(
                doc_id, {"doi": None, "year": None, "title": None}
            )
            # Duplicate manifest rows are common after resumed harvests. Keep
            # the first non-null value, but allow a later richer row to fill the
            # null year/venue left by the initial API hit.
            for key in ("doi", "year", "title"):
                if current.get(key) is None and record.get(key) is not None:
                    current[key] = record.get(key)
    return index


def reextract(
    parsed_dir: Path,
    index: dict[str, dict],
    *,
    require: tuple[str, ...] = ("activation_energy",),
) -> tuple[list[dict], ExtractionStats, list[str]]:
    """Re-run extraction over every cached document."""
    stats = ExtractionStats()
    out: list[dict] = []
    unknown: list[str] = []

    for path in sorted(parsed_dir.glob("*.md")):
        doc_id = path.stem
        meta = index.get(doc_id)
        if meta is None:
            # Fetched but never yielded a record, so no metadata was persisted.
            unknown.append(doc_id)
            meta = {"doi": None, "year": None, "title": None}
        html = path.read_text(encoding="utf-8", errors="replace")
        records = extract_records(
            html,
            doc_id=doc_id,
            doi=meta["doi"],
            year=meta["year"],
            title=meta["title"],
            require=require,
            stats=stats,
        )
        for record in merge_by_sample(records):
            payload = record.as_dict()
            payload["schema_version"] = "2.0"
            payload["extractor_version"] = __version__
            out.append(payload)
    return out, stats, unknown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parsed-dir", default="parsed")
    parser.add_argument("--index", default="facts/llzo_v1.jsonl")
    parser.add_argument("--out", default="facts/llzo_v2.jsonl")
    parser.add_argument(
        "--require",
        default="activation_energy,ionic_conductivity,total_conductivity",
        help="comma-separated; a record is kept if it has any of these",
    )
    args = parser.parse_args()

    parsed_dir = Path(args.parsed_dir)
    index = load_index(parsed_dir / "manifest.jsonl", Path(args.index))
    require = tuple(f.strip() for f in args.require.split(",") if f.strip())
    records, stats, unknown = reextract(parsed_dir, index, require=require)

    out = Path(args.out)
    text = "".join(
        json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
        for record in records
    )
    atomic_write_text(out, text)

    parsed_files = sorted(parsed_dir.glob("*.md"))
    input_manifest = file_manifest(parsed_files, root=parsed_dir)
    index_path = parsed_dir / "manifest.jsonl"
    dataset_manifest = {
        "schema_version": "1.0",
        "dataset_path": str(out),
        "dataset_sha256": sha256_file(out),
        "dataset_fingerprint": fingerprint(records),
        "extractor_version": __version__,
        "require_any": list(require),
        "records": len(records),
        "documents": len(parsed_files),
        "documents_without_metadata": unknown,
        "parsed_files": input_manifest,
        "bibliography_manifest": {
            "path": str(index_path),
            "sha256": sha256_file(index_path) if index_path.exists() else None,
        },
        "extraction_stats": asdict(stats),
        "created_unix_time": time.time(),
    }
    atomic_write_json(Path(f"{out}.manifest.json"), dataset_manifest)

    total = len(parsed_files)
    print(f"documents      : {total}")
    print(f"  no metadata  : {len(unknown)}")
    print(f"tables seen    : {stats.tables_seen}")
    print(f"tables used    : {stats.tables_used}")
    print(f"cells parsed   : {stats.cells_parsed}")
    print(f"cells dropped  : {stats.cells_dropped}")
    print(f"records written: {len(records)} -> {out}")


if __name__ == "__main__":
    main()
