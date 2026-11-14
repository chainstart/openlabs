"""Owner seats: logs and bulk files land in artifact staging, staged files get declared."""

from __future__ import annotations

import json

from openlabs import codex_hook, owner
from openlabs.attempts import _ARTIFACT_ONLY_SUFFIXES
from openlabs.contracts import RESULT_SCHEMA, atomic_write_json, validate_result_bundle

EXPECTED = {"schema_version": RESULT_SCHEMA, "task_id": "t1", "campaign_id": "c1",
            "lab_id": "ai", "domain": "ai"}


def _context(tmp_path, packet: dict) -> tuple[dict, dict]:
    workspace, staging, canonical = (tmp_path / name for name in ("ws", "stage", "canonical"))
    for root in (workspace, staging, canonical):
        root.mkdir()
    result = workspace / "attempts" / "a1" / "result.json"
    atomic_write_json(result, packet)
    context = {"result_path": str(result), "agent_workspace": str(workspace),
               "canonical_campaign_workspace": str(canonical),
               "expected_result": dict(EXPECTED), "protocol_binding": None,
               "owner": {"artifact_staging_root": str(staging), "preregistration_sha256": None,
                         "work_log": str(workspace / owner.WORK_LOG_NAME), "deadline": "x"}}
    return context, {"ws": workspace, "stage": staging, "canonical": canonical,
                     "result": result}


def _changed_bulk(paths) -> list[str]:
    """Files the commit's campaign data boundary would reject (new or changed bulk)."""

    bad = []
    for path in paths["ws"].rglob("*"):
        relative = path.relative_to(paths["ws"])
        if not path.is_file() or relative.parts[0] == "attempts":
            continue
        original = paths["canonical"] / relative
        if original.is_file() and original.read_bytes() == path.read_bytes():
            continue
        if path.stat().st_size > 5 * 1024 * 1024 or any(
                relative.as_posix().lower().endswith(s) for s in _ARTIFACT_ONLY_SUFFIXES):
            bad.append(relative.as_posix())
    return bad


def test_solver_logs_left_in_the_workspace_are_moved_and_declared(tmp_path) -> None:
    # The 2026-11-14 rejections: precheck/submit_s102.log, evidence/control_completed/solve.log.
    context, paths = _context(tmp_path, {
        "status": "frozen", "freeze_reason_class": "feasibility_precheck_failed",
        "reason": "asymmetry", "artifacts": ["evidence/control_completed/solve.log"]})
    ws, stage, canonical = paths["ws"], paths["stage"], paths["canonical"]
    (ws / "evidence" / "control_completed").mkdir(parents=True)
    (ws / "evidence" / "control_completed" / "solve.log").write_text("chain step 750\n")
    (ws / "precheck").mkdir()
    (ws / "precheck" / "submit_s102.log").write_text("submitted\n")
    (ws / "precheck" / "summary.json").write_text("{}\n")          # small text stays
    (canonical / "old.log").write_text("legacy\n")                 # unchanged legacy file stays
    (ws / "old.log").write_text("legacy\n")
    (canonical / "notes.out").write_text("v1\n")                   # changed tracked file
    (ws / "notes.out").write_text("v2\n")
    (ws / "big.dat").write_bytes(b"0" * (5 * 1024 * 1024 + 1))     # over the size limit
    (ws / owner.WORK_LOG_NAME).write_text("log\n")
    assert len(_changed_bulk(paths)) == 4

    assert codex_hook._stop_gate_problems(context) == []
    assert _changed_bulk(paths) == []
    assert (ws / "precheck" / "summary.json").is_file() and (ws / "old.log").is_file()
    assert (ws / "notes.out").read_text() == "v1\n"                 # canonical bytes restored
    assert (stage / "workspace" / "notes.out").read_text() == "v2\n"
    assert (stage / "workspace" / "evidence" / "control_completed" / "solve.log").is_file()
    stored = json.loads(paths["result"].read_text())
    assert validate_result_bundle(stored).valid, validate_result_bundle(stored).errors
    uris = {item["uri"] for item in stored["artifacts"]}
    staged = {path.resolve().as_uri() for path in stage.rglob("*") if path.is_file()}
    assert staged <= uris                                         # every staged file declared
    assert "submit_s102.log" in stored["owner_packet"]["control_note"]
    assert stored["gate_result"]["freeze_reason_class"] == "feasibility_precheck_failed"


def test_full_bundle_gets_its_undeclared_staged_logs_declared(tmp_path) -> None:
    # The 2026-11-14 rejection: "artifact staging contains files absent from
    # result.artifacts: control-65d449c0/stdout.log".
    context, paths = _context(tmp_path, {})
    (paths["stage"] / "control-65d449c0").mkdir()
    log = paths["stage"] / "control-65d449c0" / "stdout.log"
    log.write_text("done\n")
    (paths["stage"] / "replay.py").write_text("print(1)\n")       # scripts stay the owner's job
    full = {**EXPECTED, "status": "completed", "summary": "Control evaluated.",
            "artifacts": [], "claims": [], "next_actions": [], "paper_candidate": False}
    atomic_write_json(paths["result"], full)
    owner.hook_normalize(context)
    stored = json.loads(paths["result"].read_text())
    assert [item["uri"] for item in stored["artifacts"]] == [log.resolve().as_uri()]
    assert "control_note" not in stored and validate_result_bundle(stored).valid


def test_nothing_moves_without_a_staging_root(tmp_path) -> None:
    context, paths = _context(tmp_path, {"status": "continuing"})
    context["owner"]["artifact_staging_root"] = None
    (paths["ws"] / "run.log").write_text("x\n")
    owner.hook_normalize(context)
    assert (paths["ws"] / "run.log").is_file()


def test_brief_says_where_files_go(tmp_path, monkeypatch) -> None:
    from test_owner_mode import _latest, _owner_program

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _latest(db, topic["campaign_id"])
    text = owner.render_brief(
        paths, settings, task=seat, campaign=db.campaign(topic["campaign_id"]), topic=topic,
        adapter_family=None, deadline=__import__("datetime").datetime(2026, 11, 14))
    assert "small text" in text and "large-outputs dir" in text and "moved there" in text
