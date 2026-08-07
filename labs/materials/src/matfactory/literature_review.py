"""Build a cached, auditable OpenAlex corpus for materials discovery."""

from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .open_data import CachedHTTPClient
from .provenance import (
    atomic_write_json,
    atomic_write_text,
    fingerprint,
    sha256_file,
)

_ROOT = Path(__file__).resolve().parents[2]
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_OPENALEX = "https://api.openalex.org"
_USER_AGENT = "matfactory/0.2 (auditable open materials research)"


@dataclass(frozen=True)
class LiteratureProtocol:
    study_id: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    cache_dir: Path
    from_date: str
    to_date: str
    results_per_query: int
    manual_review_limit: int
    queries: tuple[dict[str, str], ...]
    seed_dois: tuple[str, ...]
    primary_terms: tuple[str, ...]
    supporting_terms: tuple[str, ...]
    exclusion_terms: tuple[str, ...]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _valid_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must use YYYY-MM-DD")
    return value


def load_literature_protocol(path: Path | str) -> LiteratureProtocol:
    """Validate the frozen search space without making network requests."""
    source = Path(path).resolve()
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError("literature protocol schema_version must be '1.0'")
    study_id = payload.get("study_id")
    if not isinstance(study_id, str) or not _SAFE_ID.fullmatch(study_id):
        raise ValueError("study_id must be a safe lowercase identifier")
    from_date = _valid_date(payload.get("from_date"), "from_date")
    to_date = _valid_date(payload.get("to_date"), "to_date")
    if from_date > to_date:
        raise ValueError("from_date must not be after to_date")

    results_per_query = payload.get("results_per_query")
    manual_review_limit = payload.get("manual_review_limit")
    if not isinstance(results_per_query, int) or not 1 <= results_per_query <= 100:
        raise ValueError("results_per_query must be an integer from 1 to 100")
    if not isinstance(manual_review_limit, int) or not 1 <= manual_review_limit <= 200:
        raise ValueError("manual_review_limit must be an integer from 1 to 200")

    queries = payload.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries must be a non-empty list")
    normalized_queries: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in queries:
        if not isinstance(row, dict):
            raise TypeError("each literature query must be an object")
        query_id = row.get("query_id")
        query = row.get("query")
        if (
            not isinstance(query_id, str)
            or not _SAFE_ID.fullmatch(query_id)
            or query_id in seen
        ):
            raise ValueError(f"unsafe or duplicate query_id {query_id!r}")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"query {query_id} must contain text")
        seen.add(query_id)
        normalized_queries.append({"query_id": query_id, "query": query.strip()})

    def term_list(field: str) -> tuple[str, ...]:
        values = payload.get(field)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(item, str) or not item.strip() for item in values)
        ):
            raise ValueError(f"{field} must be a non-empty string list")
        return tuple(dict.fromkeys(item.strip().lower() for item in values))

    seed_dois = payload.get("seed_dois", [])
    if not isinstance(seed_dois, list) or any(
        not isinstance(item, str) or not item.strip() for item in seed_dois
    ):
        raise ValueError("seed_dois must be a string list")

    return LiteratureProtocol(
        study_id=study_id,
        protocol_path=source,
        protocol_sha256=sha256_file(source),
        root_dir=_repo_path(
            str(payload.get("root_dir", f"runs/literature/{study_id}"))
        ),
        cache_dir=_repo_path(
            str(payload.get("cache_dir", f"cache/openalex/{study_id}"))
        ),
        from_date=from_date,
        to_date=to_date,
        results_per_query=results_per_query,
        manual_review_limit=manual_review_limit,
        queries=tuple(normalized_queries),
        seed_dois=tuple(item.strip().lower() for item in seed_dois),
        primary_terms=term_list("primary_terms"),
        supporting_terms=term_list("supporting_terms"),
        exclusion_terms=term_list("exclusion_terms"),
    )


def reconstruct_abstract(index: Any) -> str | None:
    """Reconstruct OpenAlex's compact inverted-index abstract."""
    if not isinstance(index, dict) or not index:
        return None
    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        positioned.extend(
            (int(position), word)
            for position in positions
            if isinstance(position, int) and position >= 0
        )
    if not positioned:
        return None
    positioned.sort()
    return " ".join(word for _position, word in positioned)


def _doi(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return (
        value.strip()
        .lower()
        .removeprefix("https://doi.org/")
        .removeprefix("http://doi.org/")
    )


def _source_name(work: dict[str, Any]) -> str | None:
    location = work.get("primary_location")
    if not isinstance(location, dict):
        return None
    source = location.get("source")
    return source.get("display_name") if isinstance(source, dict) else None


def _authors(work: dict[str, Any], limit: int = 12) -> list[str]:
    output: list[str] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and isinstance(author.get("display_name"), str):
            output.append(author["display_name"])
        if len(output) >= limit:
            break
    return output


def _keyword_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def _normalize_work(
    work: dict[str, Any],
    *,
    query_ids: set[str],
    protocol: LiteratureProtocol,
    seeded: bool,
) -> dict[str, Any]:
    title = str(work.get("title") or work.get("display_name") or "").strip()
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    title_primary = _keyword_hits(title, protocol.primary_terms)
    abstract_primary = _keyword_hits(abstract or "", protocol.primary_terms)
    supporting = _keyword_hits(f"{title} {abstract or ''}", protocol.supporting_terms)
    excluded = _keyword_hits(f"{title} {abstract or ''}", protocol.exclusion_terms)
    year = work.get("publication_year")
    citations = int(work.get("cited_by_count") or 0)
    recency = max(0.0, min((int(year or 2020) - 2020) / 6.0, 1.0))
    score = (
        6.0 * len(title_primary)
        + 2.0 * len(abstract_primary)
        + 1.0 * len(supporting)
        + 2.0 * len(query_ids)
        + recency
        + min(math.log1p(citations) / 3.0, 2.0)
        + (8.0 if seeded else 0.0)
        - 8.0 * len(excluded)
    )
    doi = _doi(work.get("doi"))
    openalex_id = str(work.get("id") or "")
    identity = doi or openalex_id
    location = work.get("primary_location") or {}
    return {
        "identity": identity,
        "openalex_id": openalex_id,
        "doi": doi,
        "title": title,
        "abstract": abstract,
        "publication_year": year,
        "publication_date": work.get("publication_date"),
        "type": work.get("type"),
        "venue": _source_name(work),
        "authors": _authors(work),
        "cited_by_count": citations,
        "is_open_access": bool((work.get("open_access") or {}).get("is_oa")),
        "landing_page_url": (
            location.get("landing_page_url") if isinstance(location, dict) else None
        ),
        "pdf_url": location.get("pdf_url") if isinstance(location, dict) else None,
        "query_ids": sorted(query_ids),
        "seeded": seeded,
        "primary_term_hits_in_title": title_primary,
        "primary_term_hits_in_abstract": abstract_primary,
        "supporting_term_hits": supporting,
        "exclusion_term_hits": excluded,
        "automated_relevance_score": score,
        "screening_status": "manual-review-required",
    }


def _query_url(protocol: LiteratureProtocol, query: str) -> str:
    params = {
        "search": query,
        "filter": (
            f"from_publication_date:{protocol.from_date},"
            f"to_publication_date:{protocol.to_date}"
        ),
        "per-page": str(protocol.results_per_query),
    }
    return f"{_OPENALEX}/works?{urllib.parse.urlencode(params)}"


def _seed_url(doi: str) -> str:
    identifier = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
    return f"{_OPENALEX}/works/{identifier}"


def build_literature_review(
    path: Path | str,
    *,
    client: CachedHTTPClient | None = None,
) -> dict[str, Any]:
    """Fetch, deduplicate, and rank a reproducible literature corpus."""
    protocol = load_literature_protocol(path)
    http = client or CachedHTTPClient(
        cache_dir=protocol.cache_dir,
        user_agent=_USER_AGENT,
        min_interval_seconds=0.15,
        timeout_seconds=45,
        max_retries=3,
    )
    raw_by_identity: dict[str, dict[str, Any]] = {}
    query_membership: dict[str, set[str]] = {}
    seeded: set[str] = set()
    source_artifacts: list[dict[str, Any]] = []

    for query in protocol.queries:
        url = _query_url(protocol, query["query"])
        payload, artifact = http.get_json(url)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("results"), list
        ):
            raise TypeError(f"OpenAlex query {query['query_id']} returned invalid data")
        source_artifacts.append(
            {
                "kind": "query",
                "query_id": query["query_id"],
                "url": url,
                "sha256": artifact.sha256,
                "cache_path": str(artifact.content_path),
                "from_cache": artifact.from_cache,
                "result_count": len(payload["results"]),
            }
        )
        for work in payload["results"]:
            if not isinstance(work, dict):
                continue
            identity = _doi(work.get("doi")) or str(work.get("id") or "")
            if not identity:
                continue
            raw_by_identity.setdefault(identity, work)
            query_membership.setdefault(identity, set()).add(query["query_id"])

    for doi in protocol.seed_dois:
        url = _seed_url(doi)
        work, artifact = http.get_json(url)
        if not isinstance(work, dict):
            raise TypeError(f"OpenAlex DOI lookup returned invalid data for {doi}")
        identity = _doi(work.get("doi")) or str(work.get("id") or doi)
        raw_by_identity[identity] = work
        query_membership.setdefault(identity, set()).add("seed")
        seeded.add(identity)
        source_artifacts.append(
            {
                "kind": "seed-doi",
                "doi": doi,
                "url": url,
                "sha256": artifact.sha256,
                "cache_path": str(artifact.content_path),
                "from_cache": artifact.from_cache,
                "result_count": 1,
            }
        )

    records = [
        _normalize_work(
            work,
            query_ids=query_membership[identity],
            protocol=protocol,
            seeded=identity in seeded,
        )
        for identity, work in raw_by_identity.items()
    ]
    records.sort(
        key=lambda row: (
            -float(row["automated_relevance_score"]),
            -(int(row["publication_year"] or 0)),
            str(row["identity"]),
        )
    )
    manual_review = records[: protocol.manual_review_limit]
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "report_kind": "materials-discovery-open-literature-corpus",
        "study_id": protocol.study_id,
        "created_unix_time": time.time(),
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "workflow_path": str(Path(__file__).resolve()),
        "workflow_sha256": sha256_file(__file__),
        "source_artifacts": source_artifacts,
        "coverage": {
            "from_date": protocol.from_date,
            "to_date": protocol.to_date,
            "n_queries": len(protocol.queries),
            "n_seed_dois": len(protocol.seed_dois),
            "n_unique_records": len(records),
            "n_manual_review_queue": len(manual_review),
            "abstract_available_fraction": (
                sum(row["abstract"] is not None for row in records) / len(records)
                if records
                else 0.0
            ),
        },
        "automation_limits": [
            "automated ranking is discovery support, not a novelty judgment",
            "citation counts and OpenAlex metadata may be incomplete or delayed",
            "every retained scientific claim requires inspection of the primary paper",
            "journal quartile and acceptance probability are not inferred from this corpus",
        ],
        "records": records,
        "manual_review_queue": [row["identity"] for row in manual_review],
        "publication_assessment": {
            "q1_claim_ready": False,
            "reason": "primary-paper claim extraction and candidate-specific novelty review remain pending",
        },
        "client_statistics": {
            "calls_made": http.calls_made,
            "cache_hits": http.cache_hits,
        },
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def render_literature_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    by_identity = {row["identity"]: row for row in report["records"]}
    lines = [
        "# Hidden-order and soft-mode literature corpus",
        "",
        f"Study: `{report['study_id']}`",
        "",
        (
            f"Coverage: {coverage['from_date']} to {coverage['to_date']}; "
            f"{coverage['n_unique_records']} unique records; "
            f"{coverage['n_manual_review_queue']} queued for manual review."
        ),
        "",
        "This is a search and prioritization artifact, not a novelty conclusion.",
        "",
        "## Manual-review queue",
        "",
        "| Rank | Year | Score | Citations | Work | Query routes |",
        "| ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for rank, identity in enumerate(report["manual_review_queue"], start=1):
        row = by_identity[identity]
        url = f"https://doi.org/{row['doi']}" if row["doi"] else row["openalex_id"]
        title = str(row["title"]).replace("|", "\\|")
        lines.append(
            f"| {rank} | {row['publication_year'] or ''} | "
            f"{row['automated_relevance_score']:.2f} | {row['cited_by_count']} | "
            f"[{title}]({url}) | {', '.join(row['query_ids'])} |"
        )
    lines.extend(["", "## Required manual decisions", ""])
    lines.extend(f"- {item}" for item in report["automation_limits"])
    return "\n".join(lines).rstrip() + "\n"


def run_literature_review(path: Path | str) -> dict[str, Any]:
    """Write a frozen corpus and refuse to overwrite changed evidence."""
    protocol = load_literature_protocol(path)
    report_path = protocol.root_dir / "review.json"
    markdown_path = protocol.root_dir / "review.md"
    records_path = protocol.root_dir / "records.jsonl"
    if report_path.exists():
        report = _read_json(report_path)
        checks = {
            "protocol": report.get("protocol_sha256") == protocol.protocol_sha256,
            "workflow": report.get("workflow_sha256") == sha256_file(__file__),
            "markdown": markdown_path.is_file(),
            "records": records_path.is_file(),
        }
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise RuntimeError(
                f"literature evidence changed ({failed}); use a new study_id/root_dir"
            )
        return report

    report = build_literature_review(protocol.protocol_path)
    records_text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in report["records"]
    )
    atomic_write_json(report_path, report)
    atomic_write_text(markdown_path, render_literature_markdown(report))
    atomic_write_text(records_path, records_text)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    protocol = load_literature_protocol(args.protocol)
    if args.list_only:
        print(
            json.dumps(
                {
                    "study_id": protocol.study_id,
                    "protocol_sha256": protocol.protocol_sha256,
                    "root_dir": str(protocol.root_dir),
                    "cache_dir": str(protocol.cache_dir),
                    "queries": list(protocol.queries),
                    "seed_dois": list(protocol.seed_dois),
                },
                indent=2,
            )
        )
        return
    print(json.dumps(run_literature_review(protocol.protocol_path), indent=2))


if __name__ == "__main__":
    main()
