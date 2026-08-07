from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.harvest import harvest  # noqa: E402
from matfactory.sciverse import Paper, SciverseError  # noqa: E402


HTML = (
    "<table><tr><td>Sample</td><td>Ea/eV</td></tr>"
    "<tr><td>LLZO</td><td>0.31</td></tr></table>"
)


class FakeClient:
    def __init__(self, *, fail_once=False):
        self.fail_once = fail_once
        self.fetches = 0
        self.paper = Paper("u1", "LLZO", "10.1/test", 2024, "doc1", "J", None)

    def iter_papers(self, *_args, **_kwargs):
        return iter([self.paper])

    def read_full_document(self, _doc_id):
        self.fetches += 1
        if self.fail_once and self.fetches == 1:
            raise SciverseError("transient")
        return HTML

    def stats(self):
        return {"api_calls": self.fetches, "cache_hits": 0}


def test_transient_failure_can_retry_on_later_query(tmp_path):
    client = FakeClient(fail_once=True)
    report = harvest(
        ["first", "second"],
        out_path=tmp_path / "facts.jsonl",
        parsed_dir=tmp_path / "parsed",
        client=client,
        verbose=False,
    )
    assert report.fetch_failures == 1
    assert report.papers_fetched == 1
    assert report.merged_records == 1
    manifest = (tmp_path / "parsed/manifest.jsonl").read_text().splitlines()
    assert len(manifest) == 1
    assert json.loads(manifest[0])["doc_id"] == "doc1"


def test_legacy_fact_file_is_never_mixed_with_new_schema(tmp_path):
    output = tmp_path / "legacy.jsonl"
    output.write_text('{"old": true}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to append"):
        harvest(
            ["q"],
            out_path=output,
            parsed_dir=tmp_path / "parsed",
            client=FakeClient(),
            verbose=False,
        )
