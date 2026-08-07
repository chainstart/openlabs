from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.literature_review import (
    build_literature_review,
    load_literature_protocol,
    reconstruct_abstract,
)
from matfactory.open_data import HTTPArtifact

PROTOCOL = ROOT / "analysis/protocols/materials_discovery_literature_v1.json"


class _FakeClient:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.calls_made = 0
        self.cache_hits = 0

    def get_json(self, url):
        self.calls_made += 1
        is_seed = "/works/https%3A" in url
        identity = "seed" if is_seed else f"query-{self.calls_made}"
        work = {
            "id": f"https://openalex.org/{identity}",
            "doi": f"https://doi.org/10.0000/{identity}",
            "title": "Vacancy ordering creates a low symmetry phase",
            "publication_year": 2026,
            "publication_date": "2026-01-01",
            "type": "article",
            "cited_by_count": 3,
            "abstract_inverted_index": {"Soft": [0], "mode": [1], "ordering": [2]},
            "authorships": [{"author": {"display_name": "A. Researcher"}}],
            "primary_location": {
                "source": {"display_name": "Journal"},
                "landing_page_url": "https://example.test/work",
                "pdf_url": None,
            },
            "open_access": {"is_oa": True},
        }
        payload = work if is_seed else {"results": [work]}
        path = self.tmp_path / f"{self.calls_made}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        artifact = HTTPArtifact(
            url=url,
            text=json.dumps(payload),
            sha256=f"sha-{self.calls_made}",
            content_path=path,
            metadata_path=path,
            from_cache=False,
        )
        return payload, artifact


def test_reconstruct_abstract_uses_positions():
    assert reconstruct_abstract({"world": [1], "hello": [0]}) == "hello world"
    assert reconstruct_abstract(None) is None


def test_protocol_has_multiple_routes_and_frozen_seed_dois():
    protocol = load_literature_protocol(PROTOCOL)
    assert len(protocol.queries) >= 6
    assert len(protocol.seed_dois) >= 5
    assert protocol.to_date == "2026-08-07"


def test_build_review_deduplicates_and_keeps_manual_gate(tmp_path):
    report = build_literature_review(PROTOCOL, client=_FakeClient(tmp_path))
    assert report["coverage"]["n_queries"] == 7
    assert report["records"]
    assert all(
        row["screening_status"] == "manual-review-required" for row in report["records"]
    )
    assert report["publication_assessment"]["q1_claim_ready"] is False
    assert any(row["seeded"] for row in report["records"])


def test_protocol_rejects_more_than_openalex_page_limit(tmp_path):
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    payload["results_per_query"] = 101
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="1 to 100"):
        load_literature_protocol(path)
