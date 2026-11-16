"""Cited inputs outside the data/artifact roots (2026-11-16).

An admission review (portfolio_review, attempt 6ea21cc5) listed the files it had read as
artifacts, among them ``task-input`` (its job packet under the instance's
database/inbox/jobs) and ``queue-source`` (build/lines/astro-survey-photometry/queue/
queue.json). The gate refused the whole result ("outside data/artifact roots") and a
second review was dispatched. Such citations are now bound by the control plane; outputs
written outside the roots, missing files and protected paths are still refused.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path

from openlabs.attempts import (
    attempt_started,
    freeze_result_bundle,
    prepare_attempt_workspace,
    publish_staged_artifacts,
)
from openlabs.contracts import sha256_file
from openlabs.engine import _bind_external_references
from openlabs.gates import (
    bind_external_references,
    evaluate_result_bundle,
    protected_reference,
)
from openlabs.spin_guard import result_products
from test_attempt_transactions import _leased_task, _paths

HOUR = 3600.0


def _age(path: Path, seconds_before: float) -> None:
    moment = time.time() - seconds_before
    os.utime(path, (moment, moment))


def _payload(artifacts: list[dict]) -> dict:
    return {
        "schema_version": "openlabs.result_bundle.v1",
        "task_id": "task",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "status": "succeeded",
        "summary": "Admission review.",
        "artifacts": artifacts,
        "claims": [{
            "claim_id": "c1", "text": "Reviewed.", "status": "supported", "limitations": [],
            "evidence": [item["artifact_id"] for item in artifacts],
        }],
        "next_actions": [],
    }


def _artifact(artifact_id: str, path: Path, kind: str = "input_source",
              sha256: str | None = None) -> dict:
    return {"artifact_id": artifact_id, "uri": path.resolve().as_uri(),
            "sha256": sha256 if sha256 is not None else sha256_file(path), "kind": kind}


def _setup(tmp_path: Path):
    paths = _paths(tmp_path)
    # As on cc-sg: the job inbox lives under the instance database, outside both roots.
    paths = dataclasses.replace(paths, inbox_root=tmp_path / "instance" / "database" / "inbox")
    paths.job_inbox.mkdir(parents=True, exist_ok=True)
    _db, task = _leased_task(paths)
    workspace = prepare_attempt_workspace(paths, task, {})
    attempt_id = str(task["current_attempt_id"])
    line_queue = tmp_path / "build" / "lines" / "astro-survey-photometry" / "queue" / "queue.json"
    line_queue.parent.mkdir(parents=True)
    line_queue.write_text(json.dumps({"candidates": []}), encoding="utf-8")
    _age(line_queue, HOUR)  # written by the line's enumerator long before the attempt
    # The job packet is written just after the attempt workspace, then the runner's request.
    job = paths.job_inbox / f"task-{attempt_id}.json"
    job.write_text(json.dumps({"task_id": "task"}), encoding="utf-8")
    request = workspace.root / "agent-request.md"
    request.write_text("request\n", encoding="utf-8")
    started = attempt_started(workspace)
    assert started is not None
    os.utime(job, (started + 0.3, started + 0.3))
    os.utime(request, (started + 0.6, started + 0.6))
    runtime = {"agent_request_path": str(request)}
    return paths, workspace, attempt_id, line_queue, job, runtime


def _roots(paths) -> tuple[Path, ...]:
    return (paths.data, paths.artifacts)


def test_the_reviews_task_input_and_queue_source_are_bound_as_references(tmp_path) -> None:
    paths, workspace, attempt_id, queue, job, runtime = _setup(tmp_path)
    payload = _payload([
        _artifact("task-input", job),
        # A mis-hashed citation of an unchanged input is corrected, not refused.
        _artifact("queue-source", queue, sha256="0" * 64),
    ])
    assert not evaluate_result_bundle(payload, allowed_roots=_roots(paths)).passed

    bound, records = _bind_external_references(
        paths, payload, roots=_roots(paths), task_id="task", attempt_id=attempt_id,
        workspace=workspace, runtime=runtime,
    )
    gate = evaluate_result_bundle(bound, allowed_roots=_roots(paths))
    assert gate.passed, gate.blockers
    by_id = {record["artifact_id"]: record for record in records}
    assert by_id["task-input"]["basis"] == "attempt_job_packet"
    assert by_id["queue-source"]["basis"] == "unchanged_since_attempt_start"
    assert by_id["queue-source"]["sha256"] == sha256_file(queue)
    assert by_id["queue-source"]["declared_sha256"] == "0" * 64
    assert by_id["queue-source"]["bytes"] == queue.stat().st_size
    # References are not products for the no-progress guard.
    assert result_products(bound) == set()

    # The immutable archive keeps a snapshot of each small reference; publication accepts it.
    archived, _path, _sha = freeze_result_bundle(
        paths, bound, attempt_id=attempt_id, source_result_path=tmp_path / "result.json",
        source_result_sha256="0" * 64,
    )
    assert evaluate_result_bundle(archived, allowed_roots=_roots(paths)).passed
    for item in archived["artifacts"]:
        assert item["external_reference"]["snapshot"] is True
        assert item["external_reference"]["source_uri"].startswith("file://")
        assert Path(item["uri"][len("file://"):]).is_relative_to(paths.artifacts.resolve())
    publish_staged_artifacts(paths, bound, archived, workspace=workspace, attempt_id=attempt_id)


def test_a_large_reference_is_bound_by_path_without_a_copy(tmp_path, monkeypatch) -> None:
    import openlabs.attempts as attempts

    paths, workspace, attempt_id, queue, _job, runtime = _setup(tmp_path)
    monkeypatch.setattr(attempts, "EXTERNAL_SNAPSHOT_MAX_BYTES", 4)
    bound, _records = _bind_external_references(
        paths, _payload([_artifact("queue-source", queue)]), roots=_roots(paths),
        task_id="task", attempt_id=attempt_id, workspace=workspace, runtime=runtime,
    )
    archived, _path, _sha = freeze_result_bundle(
        paths, bound, attempt_id=attempt_id, source_result_path=tmp_path / "result.json",
        source_result_sha256="0" * 64,
    )
    (item,) = archived["artifacts"]
    assert item["uri"] == queue.resolve().as_uri()
    assert item["external_reference"]["snapshot"] is False
    assert evaluate_result_bundle(archived, allowed_roots=_roots(paths)).passed


def test_a_file_outside_the_roots_written_during_the_attempt_is_refused(tmp_path) -> None:
    paths, workspace, attempt_id, queue, job, runtime = _setup(tmp_path)
    queue.write_text(json.dumps({"candidates": ["changed"]}), encoding="utf-8")  # now
    output = queue.parent / "new-output.json"
    output.write_text("{}", encoding="utf-8")
    payload = _payload([_artifact("queue-source", queue), _artifact("misplaced", output)])
    bound, records = _bind_external_references(
        paths, payload, roots=_roots(paths), task_id="task", attempt_id=attempt_id,
        workspace=workspace, runtime=runtime,
    )
    assert records == []
    gate = evaluate_result_bundle(bound, allowed_roots=_roots(paths))
    assert not gate.passed
    assert all("was written during this attempt" in blocker for blocker in gate.blockers)
    assert len(gate.blockers) == 2

    # The job packet changed after the agent was launched is no longer an input.
    later = float(attempt_started(workspace) or 0) + 5.0
    os.utime(job, (later, later))
    bound, records = _bind_external_references(
        paths, _payload([_artifact("task-input", job)]), roots=_roots(paths), task_id="task",
        attempt_id=attempt_id, workspace=workspace, runtime=runtime,
    )
    assert records == [] and not evaluate_result_bundle(
        bound, allowed_roots=_roots(paths)).passed


def test_missing_and_protected_paths_are_refused(tmp_path) -> None:
    paths, workspace, attempt_id, queue, _job, runtime = _setup(tmp_path)
    secret = tmp_path / "keys" / ".ssh" / "id_ed25519"
    secret.parent.mkdir(parents=True)
    secret.write_text("not a key\n", encoding="utf-8")
    _age(secret, HOUR)
    missing = queue.parent / "gone.json"
    payload = _payload([
        _artifact("secret", secret),
        {"artifact_id": "gone", "uri": missing.as_uri(), "sha256": "1" * 64, "kind": "x"},
    ])
    # An agent cannot pre-mark a file as a reference: its own marks are dropped.
    payload["artifacts"][0]["external_reference"] = {
        "schema_version": "openlabs.external_reference.v1", "path": str(secret.resolve()),
        "sha256": sha256_file(secret)}
    bound, records = _bind_external_references(
        paths, payload, roots=_roots(paths), task_id="task", attempt_id=attempt_id,
        workspace=workspace, runtime=runtime,
    )
    assert records == []
    gate = evaluate_result_bundle(bound, allowed_roots=_roots(paths))
    assert not gate.passed
    assert any("secret is in a protected location" in item for item in gate.blockers)
    assert any("gone is outside data/artifact roots and does not exist" in item
               for item in gate.blockers)


def test_the_refusal_list() -> None:
    for text in (
        "/workspace/secret-key/LATEST.txt",
        "/workspace/secret-key",
        "/home/node/.claude/settings.json",
        "/root/.bashrc",
        "/etc/passwd",
        "/proc/self/environ",
        "/workspace/openlabs/build/lines/x/.env",
        "/workspace/openlabs/build/lines/x/deploy.pem",
        "/workspace/openlabs/openlabs-instances/cc-sg/database/live/factory.sqlite",
        "/workspace/project/.git/config",
        "/workspace/project/.codex/auth.json",
    ):
        assert protected_reference(Path(text)), text
    for text in (
        "/workspace/openlabs/build/lines/astro-survey-photometry/queue/queue.json",
        "/workspace/openlabs/openlabs-instances/cc-sg/database/inbox/jobs/t-a.json",
        "/workspace/openlabs/build/lines/astro-survey-photometry/venues/apss_howto.html",
    ):
        assert not protected_reference(Path(text)), text


def test_without_an_attempt_start_the_strict_rule_holds(tmp_path) -> None:
    queue = tmp_path / "outside" / "queue.json"
    queue.parent.mkdir()
    queue.write_text("{}", encoding="utf-8")
    _age(queue, HOUR)
    roots = (tmp_path / "data", tmp_path / "artifacts")
    bound, records = bind_external_references(
        _payload([_artifact("queue-source", queue)]), allowed_roots=roots, started=None)
    assert records == []
    gate = evaluate_result_bundle(bound, allowed_roots=roots)
    assert not gate.passed and "outside data/artifact roots" in gate.blockers[0]
