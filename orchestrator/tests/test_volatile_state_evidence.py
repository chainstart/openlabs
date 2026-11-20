"""Cited live run state is bound by existence, not by a byte-for-byte hash (2026-11-20).

topic-scout:716673eb (power-market-backtest) cited, among its inputs, the instance topic
ledger (registry/instances/cc-sg/topic-ledger.json, inside the data root) and the line's
queue (build/lines/power-market-backtest/queue/queue.json, outside the roots). The queue was
rebuilt while the scout ran and the ledger changed with the scheduler's ticks, so the
result gate refused the whole result: "artifact topic-queue is outside data/artifact roots
and was written during this attempt ...; artifact topic-ledger SHA-256 mismatch".

Such documents are now bound by existence with the declared and observed hashes recorded,
and the immutable archive keeps the bytes as they were at ingest. A manuscript or data file
inside the roots that changes still fails the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from openlabs.attempts import freeze_result_bundle, publish_staged_artifacts
from openlabs.contracts import sha256_file
from openlabs.engine import _bind_external_references
from openlabs.gates import evaluate_result_bundle, volatile_state_file
from openlabs.spin_guard import result_products
from test_external_references import HOUR, _age, _artifact, _payload, _roots, _setup


def _incident(tmp_path: Path):
    paths, workspace, attempt_id, _input, _job, runtime = _setup(tmp_path)
    ledger = paths.data / "registry" / "instances" / "cc-sg" / "topic-ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"topics": [{"topic_id": "t1"}]}), encoding="utf-8")
    _age(ledger, HOUR)
    queue = tmp_path / "build" / "lines" / "power-market-backtest" / "queue" / "queue.json"
    queue.parent.mkdir(parents=True)
    queue.write_text(json.dumps({"entries": ["a"]}), encoding="utf-8")
    _age(queue, HOUR)
    manuscript = paths.data / "papers" / "p1" / "manuscript.tex"
    manuscript.parent.mkdir(parents=True)
    manuscript.write_text("\\section{Result}\n", encoding="utf-8")
    _age(manuscript, HOUR)
    # The scout reads and hashes its inputs ...
    payload = _payload([
        _artifact("topic-ledger", ledger, kind="input_reference"),
        _artifact("topic-queue", queue, kind="input_reference"),
    ])
    # ... then, while it is still running, a tick rewrites the ledger and the queue is rebuilt.
    ledger.write_text(json.dumps({"topics": [{"topic_id": "t1"}, {"topic_id": "t2"}]}),
                      encoding="utf-8")
    queue.write_text(json.dumps({"entries": ["a", "b"]}), encoding="utf-8")
    return paths, workspace, attempt_id, runtime, ledger, queue, manuscript, payload


def test_the_scouts_ledger_and_queue_citations_pass_the_gate(tmp_path) -> None:
    paths, workspace, attempt_id, runtime, ledger, queue, _ms, payload = _incident(tmp_path)
    declared = {item["artifact_id"]: item["sha256"] for item in payload["artifacts"]}

    # The original refusal, reproduced on the unbound result.
    strict = evaluate_result_bundle(payload, allowed_roots=_roots(paths))
    assert "artifact topic-ledger SHA-256 mismatch" in strict.blockers

    bound, records = _bind_external_references(
        paths, payload, roots=_roots(paths), task_id="task", attempt_id=attempt_id,
        workspace=workspace, runtime=runtime,
    )
    gate = evaluate_result_bundle(bound, allowed_roots=_roots(paths))
    assert gate.passed, gate.blockers
    by_id = {record["artifact_id"]: record for record in records}
    assert by_id["topic-ledger"]["inside_roots"] is True
    assert by_id["topic-queue"]["inside_roots"] is False
    for artifact_id, path in (("topic-ledger", ledger), ("topic-queue", queue)):
        record = by_id[artifact_id]
        assert record["basis"] == "volatile_runtime_state"
        assert record["declared_sha256"] == declared[artifact_id]
        assert record["sha256"] == sha256_file(path)
        assert record["modified_during_attempt"] is True
    # Cited state is not a product for the no-progress guard.
    assert result_products(bound) == set()

    # Another tick between the gate and the archive: the archive copies the bytes once.
    ledger.write_text(json.dumps({"topics": []}), encoding="utf-8")
    archived, _path, _sha = freeze_result_bundle(
        paths, bound, attempt_id=attempt_id, source_result_path=tmp_path / "result.json",
        source_result_sha256="0" * 64,
    )
    again = evaluate_result_bundle(archived, allowed_roots=_roots(paths))
    assert again.passed, again.blockers
    items = {item["artifact_id"]: item for item in archived["artifacts"]}
    for item in items.values():
        copy = Path(item["uri"][len("file://"):])
        assert copy.is_relative_to(paths.artifacts.resolve())
        assert sha256_file(copy) == item["sha256"] == item["volatile_state"]["sha256"]
    assert items["topic-ledger"]["sha256"] == sha256_file(ledger)
    assert items["topic-queue"]["external_reference"]["snapshot"] is True
    assert not list(Path(_path).parent.glob(".volatile-*"))
    publish_staged_artifacts(paths, bound, archived, workspace=workspace, attempt_id=attempt_id)


def test_stable_evidence_keeps_the_strict_hash_rule(tmp_path) -> None:
    paths, workspace, attempt_id, runtime, _l, _q, manuscript, _p = _incident(tmp_path)
    payload = _payload([_artifact("manuscript", manuscript, kind="manuscript")])
    manuscript.write_text("\\section{Changed}\n", encoding="utf-8")
    # A forged volatile mark on an ordinary file changes nothing.
    payload["artifacts"][0]["volatile_state"] = {
        "schema_version": "openlabs.volatile_state_reference.v1",
        "path": str(manuscript.resolve()),
    }
    bound, records = _bind_external_references(
        paths, payload, roots=_roots(paths), task_id="task", attempt_id=attempt_id,
        workspace=workspace, runtime=runtime,
    )
    assert records == []
    assert "volatile_state" not in bound["artifacts"][0]
    gate = evaluate_result_bundle(bound, allowed_roots=_roots(paths))
    assert gate.blockers == ("artifact manuscript SHA-256 mismatch",)
    # Nor does it when the gate sees the unbound payload with the mark still on it.
    assert not evaluate_result_bundle(payload, allowed_roots=_roots(paths)).passed


def test_a_missing_run_state_file_is_still_refused(tmp_path) -> None:
    paths, workspace, attempt_id, runtime, ledger, _q, _ms, _p = _incident(tmp_path)
    gone = ledger.with_name("gone") / "topic-ledger.json"
    payload = _payload([{"artifact_id": "ledger", "uri": gone.as_uri(), "sha256": "1" * 64,
                         "kind": "input_reference"}])
    bound, records = _bind_external_references(
        paths, payload, roots=_roots(paths), task_id="task", attempt_id=attempt_id,
        workspace=workspace, runtime=runtime,
    )
    assert records == []
    assert evaluate_result_bundle(bound, allowed_roots=_roots(paths)).blockers == (
        "artifact ledger does not exist",)


def test_which_files_are_live_run_state() -> None:
    for text in (
        "/workspace/openlabs/openlabs-data/registry/instances/cc-sg/topic-ledger.json",
        "/workspace/openlabs/openlabs-data/registry/topic-ledger.json",
        "/workspace/openlabs/openlabs-data/registry/instances/cc-sg/reusable-assets.json",
        "/workspace/openlabs/openlabs-data/registry/journal-rejections.json",
        "/workspace/openlabs/build/lines/power-market-backtest/queue/queue.json",
        "/workspace/openlabs/openlabs-instances/cc-sg/state/last-tick.json",
    ):
        assert volatile_state_file(Path(text)), text
    for text in (
        "/workspace/openlabs/build/lines/power-market-backtest/data/MANIFEST.json",
        "/workspace/openlabs/build/lines/x/queue/candidates.json",
        "/workspace/openlabs/build/lines/x/results/queue.json",
        "/workspace/project/topic-ledger.json",
        "/workspace/openlabs/openlabs-data/registry/settings.yaml",
        "/workspace/openlabs/openlabs-data/papers/p1/manuscript.tex",
    ):
        assert not volatile_state_file(Path(text)), text
