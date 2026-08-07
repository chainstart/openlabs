"""Harvest solid-electrolyte conductivity records from the Sciverse corpus.

Pipeline: search -> dedup -> fetch full text -> extract tables -> normalise
-> write JSONL with provenance.

Run:
    python -m matfactory.harvest --limit 100 --out facts/llzo.jsonl

Every emitted record carries (doi, doc_id, table_offset) so any number can be
re-fetched from the source document and checked. Records are written as they
are produced, so an interrupted run loses nothing and can be resumed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .provenance import atomic_write_json, atomic_write_text, fingerprint, sha256_file
from .sciverse import SciverseClient, SciverseError, SciverseFetchUnavailable
from .tables import ExtractionStats, extract_records, merge_by_sample

# Query set for the first domain. Several angles are needed because semantic
# and BM25 recall differ, and each query surfaces a partly disjoint slice.
DEFAULT_QUERIES = [
    "lithium garnet LLZO solid electrolyte ionic conductivity activation energy",
    "argyrodite Li6PS5Cl solid electrolyte ionic conductivity activation energy",
    "NASICON LATP LAGP solid electrolyte conductivity activation energy",
    "perovskite lithium lanthanum titanate LLTO ionic conductivity",
    "sulfide solid electrolyte Li10GeP2S12 LGPS conductivity activation energy",
    "halide solid electrolyte Li3InCl6 Li3YCl6 ionic conductivity",
    "sodium solid electrolyte NASICON beta-alumina ionic conductivity",
    "doped LLZO Arrhenius activation energy impedance spectroscopy",
]


@dataclass
class HarvestReport:
    queries: int = 0
    papers_seen: int = 0
    papers_with_fulltext: int = 0
    papers_fetched: int = 0
    papers_with_records: int = 0
    fetch_failures: int = 0
    fetch_unavailable: int = 0
    fetch_skipped_dead: int = 0
    query_failures: int = 0
    records: int = 0
    merged_records: int = 0
    complete_pairs: int = 0
    api_calls: int = 0
    cache_hits: int = 0
    seconds: float = 0.0
    extraction: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "queries": self.queries,
            "papers_seen": self.papers_seen,
            "papers_with_fulltext": self.papers_with_fulltext,
            "papers_fetched": self.papers_fetched,
            "papers_with_records": self.papers_with_records,
            "fetch_failures": self.fetch_failures,
            "fetch_unavailable": self.fetch_unavailable,
            "fetch_skipped_dead": self.fetch_skipped_dead,
            "query_failures": self.query_failures,
            "records": self.records,
            "merged_records": self.merged_records,
            "complete_pairs": self.complete_pairs,
            "api_calls": self.api_calls,
            "cache_hits": self.cache_hits,
            "seconds": round(self.seconds, 1),
            "extraction": self.extraction,
        }


def harvest(
    queries: list[str] | None = None,
    *,
    limit_per_query: int = 40,
    year_min: int | None = 2010,
    out_path: Path | str = "facts/records.jsonl",
    parsed_dir: Path | str | None = "parsed",
    client: SciverseClient | None = None,
    verbose: bool = True,
) -> HarvestReport:
    """Search, fetch, extract, and write records for each query."""
    queries = queries or DEFAULT_QUERIES
    client = client or SciverseClient()
    report = HarvestReport(queries=len(queries))
    stats = ExtractionStats()
    started = time.monotonic()

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    extraction_schema = {
        "schema_version": "2.0",
        "matfactory_version": __version__,
        "extractor_sha256": sha256_file(Path(__file__).with_name("tables.py")),
        "require_any": [
            "activation_energy",
            "ionic_conductivity",
            "total_conductivity",
        ],
    }
    extraction_schema["fingerprint"] = fingerprint(extraction_schema)
    schema_path = Path(f"{out_file}.schema.json")
    if out_file.exists() and out_file.stat().st_size:
        if not schema_path.exists():
            raise RuntimeError(
                f"refusing to append current extraction rules to legacy {out_file}; "
                "choose a new output path and rebuild a formal dataset with reextract"
            )
        existing_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if existing_schema.get("fingerprint") != extraction_schema["fingerprint"]:
            raise RuntimeError(
                f"extractor/schema changed for {out_file}; choose a new output path"
            )
    else:
        atomic_write_json(schema_path, extraction_schema)
    parsed_root = Path(parsed_dir) if parsed_dir else None
    if parsed_root:
        parsed_root.mkdir(parents=True, exist_ok=True)
    manifest_path = parsed_root / "manifest.jsonl" if parsed_root else None
    manifest_records: dict[str, dict[str, Any]] = {}
    if manifest_path and manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("doc_id"):
                current = manifest_records.setdefault(row["doc_id"], {})
                for key, value in row.items():
                    if value is not None:
                        current[key] = value

    # Resume support: skip documents already present in the output file.
    done_docs: set[str] = set()
    if out_file.exists():
        for line in out_file.read_text(encoding="utf-8").splitlines():
            try:
                done_docs.add(json.loads(line).get("doc_id") or "")
            except json.JSONDecodeError:
                continue
        if verbose and done_docs:
            _log(f"resuming: {len(done_docs)} documents already extracted")

    seen_docs: set[str] = set(done_docs)

    # Documents whose fulltext the API cannot serve. Roughly four in five
    # search hits fall in this bucket, so persisting the list across runs is
    # what makes a large harvest affordable at all.
    dead: set[str] = set()
    dead_path = parsed_root / "unavailable.txt" if parsed_root else None
    if dead_path and dead_path.exists():
        dead = {
            line.strip()
            for line in dead_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        if verbose and dead:
            _log(f"skipping {len(dead)} documents with no retrievable fulltext")

    # Documents already fetched and cached on disk can be re-parsed offline, so
    # they must not be re-downloaded either.
    if parsed_root:
        for path in parsed_root.glob("*.md"):
            seen_docs.add(path.stem)

    with out_file.open("a", encoding="utf-8") as sink:
        for query in queries:
            if verbose:
                _log(f"query: {query[:64]}")
            try:
                papers = list(
                    client.iter_papers(
                        query,
                        limit=limit_per_query,
                        year_min=year_min,
                        fulltext_only=True,
                    )
                )
            except Exception as exc:
                # One bad query (or a truncated response the retries could not
                # recover) must not discard the records already harvested.
                report.query_failures += 1
                _log(f"  search failed, skipping query: {exc!r}")
                continue

            report.papers_seen += len(papers)
            report.papers_with_fulltext += sum(1 for p in papers if p.has_fulltext)

            for paper in papers:
                if not paper.doc_id or paper.doc_id in seen_docs:
                    continue
                if paper.doc_id in dead:
                    report.fetch_skipped_dead += 1
                    continue
                try:
                    html = client.read_full_document(paper.doc_id)
                except SciverseFetchUnavailable:
                    # Permanently unavailable: remember it so later runs spend
                    # their budget on documents that can actually be read.
                    report.fetch_unavailable += 1
                    dead.add(paper.doc_id)
                    if dead_path:
                        atomic_write_text(
                            dead_path, "".join(f"{value}\n" for value in sorted(dead))
                        )
                    seen_docs.add(paper.doc_id)
                    continue
                except Exception as exc:
                    report.fetch_failures += 1
                    if verbose:
                        _log(f"  fetch failed {paper.doc_id[:12]}: {exc}")
                    # Do not mark transient failures seen: another query in the
                    # same run may retry the document after the service recovers.
                    continue
                report.papers_fetched += 1
                seen_docs.add(paper.doc_id)

                if parsed_root and html:
                    atomic_write_text(parsed_root / f"{paper.doc_id}.md", html)
                    # Record the bibliography for every fetched paper, not just
                    # the ones that yield facts. Without this, a paper that
                    # extracts nothing today loses its DOI, and a later parser
                    # fix cannot re-attribute the records it then finds.
                    manifest_records[paper.doc_id] = {
                        "doc_id": paper.doc_id,
                        "doi": paper.doi,
                        "year": paper.year,
                        "title": paper.title,
                        "venue": paper.venue,
                    }
                    atomic_write_text(
                        manifest_path,
                        "".join(
                            json.dumps(manifest_records[key], ensure_ascii=False)
                            + "\n"
                            for key in sorted(manifest_records)
                        ),
                    )

                records = extract_records(
                    html,
                    doc_id=paper.doc_id,
                    doi=paper.doi,
                    year=paper.year,
                    title=paper.title,
                    require=("activation_energy", "ionic_conductivity",
                             "total_conductivity"),
                    stats=stats,
                )
                if not records:
                    continue

                merged = merge_by_sample(records)
                report.papers_with_records += 1
                report.records += len(records)
                report.merged_records += len(merged)

                for record in merged:
                    payload = record.as_dict()
                    payload["query"] = query
                    if _is_complete(record):
                        report.complete_pairs += 1
                    sink.write(json.dumps(payload, ensure_ascii=False) + "\n")
                sink.flush()

                if verbose:
                    _log(
                        f"  {paper.doi or paper.doc_id[:12]} "
                        f"({paper.year}): {len(merged)} records"
                    )

    report.seconds = time.monotonic() - started
    api = client.stats()
    report.api_calls = api["api_calls"]
    report.cache_hits = api["cache_hits"]
    report.extraction = {
        "tables_seen": stats.tables_seen,
        "tables_used": stats.tables_used,
        "cells_parsed": stats.cells_parsed,
        "cells_dropped": stats.cells_dropped,
    }
    return report


def _is_complete(record) -> bool:
    """A record usable for the MLIP comparison: Ea plus a conductivity."""
    props = record.properties
    has_energy = "activation_energy" in props
    has_sigma = any(
        key in props
        for key in ("total_conductivity", "ionic_conductivity", "bulk_conductivity")
    )
    return has_energy and has_sigma


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40,
                        help="papers per query (default 40)")
    parser.add_argument("--year-min", type=int, default=2010)
    parser.add_argument("--out", default="facts/records.jsonl")
    parser.add_argument("--parsed-dir", default="parsed")
    parser.add_argument("--report", default="logs/harvest_report.json")
    parser.add_argument("--query", action="append",
                        help="override the default query set (repeatable)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = harvest(
            queries=args.query,
            limit_per_query=args.limit,
            year_min=args.year_min,
            out_path=args.out,
            parsed_dir=args.parsed_dir,
            verbose=not args.quiet,
        )
    except SciverseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = json.dumps(report.as_dict(), indent=2, ensure_ascii=False)
    print(summary)
    report_path = Path(args.report)
    atomic_write_text(report_path, summary + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
