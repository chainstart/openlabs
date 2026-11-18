"""Undeclared files in artifact staging are registered or collapsed, not a replan.

Fixture shape: await:f501e220 (2026-11-16T19:44Z). The owner staged two remote-job
packing directories (``profile_job_0/``, ``profile_job_1/``: copies of the line's
``astrosolve`` and ``contact_photometry`` code, ``run.sh``, ``plan.json``, ``lc.fits`` and a
passband table) next to the declared ``profile_job_*.tar.gz``, plus an undeclared
``refine_result/`` tree; the commit refused the whole result for 68 undeclared files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openlabs import attempts, owner
from openlabs.attempts import (
    STAGING_UNLISTED_ASIDE,
    STAGING_UNLISTED_KIND,
    STAGING_UNLISTED_MANIFEST_KIND,
    AttemptWorkspaceError,
    classify_unlisted_staging,
    settle_unlisted_staging,
    shared_code_index,
)
from openlabs.contracts import sha256_file

SOLVER_FILES = {
    "astrosolve/__init__.py": "VERSION = 1\n",
    "astrosolve/fit.py": "def fit():\n    return 0\n",
    "contact_photometry/toolkit/qprofile_run.py": "def stage():\n    pass\n",
    "contact_photometry/API.md": "# API\n",
}


def _solver(tmp_path: Path) -> Path:
    root = tmp_path / "lines" / "astro" / "solver"
    for relative, text in SOLVER_FILES.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text)
    return root


def _job_dir(stage: Path, name: str, solver: Path) -> None:
    job = stage / name
    for relative in SOLVER_FILES:
        (job / relative).parent.mkdir(parents=True, exist_ok=True)
        (job / relative).write_bytes((solver / relative).read_bytes())
    (job / "astrosolve" / "__pycache__").mkdir()
    (job / "astrosolve" / "__pycache__" / "fit.cpython-312.pyc").write_bytes(b"\0pyc")
    (job / "run.sh").write_text("python -m astrosolve\n")
    (job / "plan.json").write_text(json.dumps({"q": [0.1, 0.2]}))
    (job / "lc.fits").write_bytes(b"F" * 2048)
    (job / "passbands").mkdir()
    (job / "passbands" / "tess_t.fits.gz").write_bytes(b"P" * 4096)


def _artifact(path: Path, artifact_id: str) -> dict:
    return {"artifact_id": artifact_id, "kind": "data", "uri": path.resolve().as_uri(),
            "sha256": sha256_file(path)}


def _f501e220_stage(tmp_path: Path) -> tuple[Path, Path, dict]:
    solver = _solver(tmp_path)
    attempt = tmp_path / "attempt"
    stage = attempt / "artifact-stage"
    stage.mkdir(parents=True)
    _job_dir(stage, "profile_job_0", solver)
    _job_dir(stage, "profile_job_1", solver)
    (stage / "profile_job_0.tar.gz").write_bytes(b"T0" * 100)
    (stage / "profile_job_1.tar.gz").write_bytes(b"T1" * 100)
    (stage / "reference_s98.fits").write_bytes(b"R" * 512)
    outputs = stage / "refine_result" / "outputs" / "TIC260161938_S98_precheck"
    outputs.mkdir(parents=True)
    (outputs / "refine.json").write_text("{}\n")
    (stage / "refine_result" / "receipt.json").write_text("{}\n")
    (stage / "refine_result" / "stdout.log").write_text("")
    (stage / "refine_result" / "stderr.log").write_text("")
    payload = {"campaign_id": "c1", "task_id": "await:f501e220", "status": "awaiting_remote",
               "artifacts": [_artifact(stage / "profile_job_0.tar.gz", "profile_job_0.tar"),
                             _artifact(stage / "profile_job_1.tar.gz", "profile_job_1.tar"),
                             _artifact(stage / "reference_s98.fits", "reference_s98")]}
    return stage, solver, payload


def _staged_uris(stage: Path) -> set[str]:
    return {path.resolve().as_uri() for path in stage.rglob("*") if path.is_file()}


def test_job_bundles_collapse_to_one_manifest_each_and_the_rest_is_registered(tmp_path):
    stage, solver, payload = _f501e220_stage(tmp_path)
    index = shared_code_index([solver])
    plan = classify_unlisted_staging(stage, payload["artifacts"], shared_index=index)
    assert sorted(plan["groups"]) == ["job-bundle:profile_job_0", "job-bundle:profile_job_1"]
    assert len(plan["groups"]["job-bundle:profile_job_0"]) == 9   # code, cache, run.sh, data
    assert sorted(p.relative_to(stage).as_posix() for p, _ in plan["individual"]) == [
        "refine_result/outputs/TIC260161938_S98_precheck/refine.json",
        "refine_result/receipt.json", "refine_result/stderr.log", "refine_result/stdout.log"]

    settled, record = settle_unlisted_staging(payload, stage, shared_index=index)
    assert record is not None and record["refused"] == []
    by_kind: dict[str, list[dict]] = {}
    for item in settled["artifacts"]:
        by_kind.setdefault(item["kind"], []).append(item)
    assert len(by_kind["data"]) == 3                              # owner's own, unchanged
    assert len(by_kind[STAGING_UNLISTED_KIND]) == 4
    assert len(by_kind[STAGING_UNLISTED_MANIFEST_KIND]) == 2
    ids = [item["artifact_id"] for item in settled["artifacts"]]
    assert len(ids) == len(set(ids))                              # empty logs: distinct ids
    # Every file left in staging is declared, so the commit's check passes.
    assert _staged_uris(stage) <= {item["uri"] for item in settled["artifacts"]}
    assert not (stage / "profile_job_0").exists() or not any(
        p.is_file() for p in (stage / "profile_job_0").rglob("*"))
    moved = tmp_path / "attempt" / STAGING_UNLISTED_ASIDE / "profile_job_0" / "astrosolve"
    assert (moved / "fit.py").read_text() == SOLVER_FILES["astrosolve/fit.py"]
    manifest_entry = next(m for m in record["manifests"]
                          if m["group"] == "job-bundle:profile_job_0")
    manifest = json.loads(Path(next(
        item["uri"] for item in by_kind[STAGING_UNLISTED_MANIFEST_KIND]
        if item["artifact_id"] == manifest_entry["artifact_id"])[7:]).read_text())
    assert manifest["file_count"] == 9 == manifest_entry["file_count"]
    assert manifest["total_bytes"] == manifest_entry["total_bytes"] > 6000
    assert manifest["archived"] is False
    shared = {f["relative"]: f["shared_code"] for f in manifest["files"]}
    assert shared["profile_job_0/astrosolve/fit.py"] == ["astrosolve/fit.py"]
    assert shared["profile_job_0/plan.json"] is None
    # Settling again finds nothing new.
    assert settle_unlisted_staging(settled, stage, shared_index=index)[1] is None


def test_commit_accepts_the_settled_staging(tmp_path):
    stage, solver, payload = _f501e220_stage(tmp_path)
    settled, _record = settle_unlisted_staging(
        payload, stage, shared_index=shared_code_index([solver]))
    declared = attempts._artifact_declared_sources(settled)
    staged = {p.resolve() for p in stage.rglob("*") if p.is_file()}
    assert staged and staged <= set(declared)


def test_scripts_caches_and_over_limit_files_outside_bundles_become_manifests(tmp_path):
    stage = tmp_path / "attempt" / "artifact-stage"
    stage.mkdir(parents=True)
    (stage / "replay.py").write_text("print(1)\n")
    (stage / "__pycache__").mkdir()
    (stage / "__pycache__" / "replay.cpython-312.pyc").write_bytes(b"\0")
    (stage / "big.npz").write_bytes(b"B" * 3000)
    (stage / "a.json").write_text("{}")
    (stage / "b.json").write_text("[]")
    plan = classify_unlisted_staging(stage, [], shared_index={}, max_file_bytes=2000,
                                     max_total_bytes=10_000, max_files=1)
    assert sorted(plan["groups"]) == ["interpreter-cache", "over-limit", "unlisted-scripts"]
    assert [m["relative"] for m in plan["groups"]["over-limit"]] == ["b.json", "big.npz"]
    assert [p.name for p, _ in plan["individual"]] == ["a.json"]
    settled, record = settle_unlisted_staging({"artifacts": []}, stage, shared_index={},
                                              max_file_bytes=2000, max_files=1)
    assert len(record["manifests"]) == 3 and len(record["registered"]) == 1
    assert _staged_uris(stage) <= {item["uri"] for item in settled["artifacts"]}


def test_sensitive_names_and_symlinks_are_still_refused(tmp_path):
    from openlabs.attempts import AttemptWorkspace, publish_staged_artifacts

    root = tmp_path / "attempt"
    stage = root / "artifact-stage"
    stage.mkdir(parents=True)
    (stage / "id_rsa").write_text("key")
    (stage / "results.sqlite").write_bytes(b"db")     # ordinary output, not a credential
    settled, record = settle_unlisted_staging({"artifacts": []}, stage, shared_index={})
    assert record["refused"] == ["id_rsa"]
    assert [Path(item["uri"]).name for item in settled["artifacts"]] == ["results.sqlite"]
    workspace = AttemptWorkspace(root=root, domain_root=root, campaign_root=root / "c",
                                 canonical_domain_root=root, canonical_campaign_root=root,
                                 metadata_path=root / "attempt-workspace.json")
    (root / "attempt-workspace.json").write_text(json.dumps(
        {"artifact_policy": {"schema_version": attempts.ARTIFACT_POLICY_SCHEMA}}))
    with pytest.raises(AttemptWorkspaceError, match="protected .*id_rsa"):
        publish_staged_artifacts(None, settled, settled, workspace=workspace,  # type: ignore
                                 attempt_id="a1")
    (stage / "id_rsa").rename(tmp_path / "id_rsa")
    (stage / "link").symlink_to(tmp_path / "id_rsa")
    settled, _record = settle_unlisted_staging(settled, stage, shared_index={})
    assert all(not item["uri"].endswith("/link") for item in settled["artifacts"])
    with pytest.raises(AttemptWorkspaceError, match="symlinks"):
        publish_staged_artifacts(None, settled, settled, workspace=workspace,  # type: ignore
                                 attempt_id="a1")


def test_owner_hook_lists_only_individual_files_and_leaves_bundles(tmp_path, monkeypatch):
    stage, solver, payload = _f501e220_stage(tmp_path)
    monkeypatch.setattr(attempts, "SHARED_CODE_GLOBS", (str(solver),))
    listed = owner._with_staged(payload["artifacts"], stage)
    names = {Path(item["uri"]).name for item in listed}
    assert "fit.py" not in names and "lc.fits" not in names and "run.sh" not in names
    assert {"refine.json", "receipt.json", "stdout.log", "stderr.log"} <= names
    assert all(item["kind"] == STAGING_UNLISTED_KIND for item in listed[3:])


def test_owner_seat_with_job_bundles_in_staging_is_committed(tmp_path, monkeypatch):
    from openlabs.attempts import prepare_attempt_workspace
    from openlabs.contracts import RECEIPT_SCHEMA, atomic_write_json
    from test_owner_mode import _first_seat, _owner_program
    from test_research_program_flow import _tick

    solver = _solver(tmp_path)
    monkeypatch.setattr(attempts, "SHARED_CODE_GLOBS", (str(solver),))
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    attempt_id = str(seat["current_attempt_id"])
    workspace = prepare_attempt_workspace(paths, seat, db.campaign(seat["campaign_id"]))
    stage = workspace.artifact_staging_root
    stage.mkdir(parents=True, exist_ok=True)
    _job_dir(stage, "profile_job_0", solver)
    (stage / "profile_job_0.tar.gz").write_bytes(b"T0" * 100)
    (stage / "refine_result").mkdir()
    (stage / "refine_result" / "stdout.log").write_text("")
    output = workspace.campaign_root / "results" / "seat" / "result.json"
    db.bind_attempt_spec(seat["task_id"], attempt_id=attempt_id, lab_id="ai",
                         output_path=str(output))
    db.mark_running(seat["task_id"], attempt_id=attempt_id, owner="test", pid=1,
                    lease_seconds=600)
    atomic_write_json(output, {"status": "continuing", "summary": "profiles staged",
                               "artifacts": [{"uri": str(stage / "profile_job_0.tar.gz")}]})
    atomic_write_json(paths.result_inbox / f"{attempt_id}.json", {
        "schema_version": RECEIPT_SCHEMA, "task_id": seat["task_id"],
        "attempt_id": attempt_id, "campaign_id": seat["campaign_id"], "lab_id": "ai",
        "domain": seat["domain"], "agent_role": seat["agent_role"],
        "result_path": str(output), "sha256": sha256_file(output),
        "runtime": {"duration_seconds": 10.0, "exit_code": 0, "runner": seat["runner"],
                    "session_id": "s1"}})
    _tick(paths, settings, monkeypatch)
    assert db.task(seat["task_id"])["status"] == "succeeded", db.task(seat["task_id"])
    events = [e for e in db.events(entity_type="task", entity_id=seat["task_id"])
              if e["event_type"] == "staging_unlisted_registered"]
    assert len(events) == 1
    payload = events[0]["payload"] if "payload" in events[0] else events[0]
    text = json.dumps(payload, default=str)
    assert "job-bundle:profile_job_0" in text
