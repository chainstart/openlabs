"""Owner seats: logs and bulk files land in artifact staging, staged files get declared."""

from __future__ import annotations

import json
from pathlib import Path

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
    assert "small text" in text and "campaign data dir" in text and "one root" in text
    assert "large-outputs" not in text


def test_brief_and_review_notes_carry_the_writing_rules(tmp_path, monkeypatch) -> None:
    # User decision 2026-11-19: the readability skill binds the one writer; it is read before
    # drafting and before every revision, and review requests default to appendix/response.
    from test_owner_mode import _latest, _owner_program

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _latest(db, topic["campaign_id"])
    text = owner.render_brief(
        paths, settings, task=seat, campaign=db.campaign(topic["campaign_id"]), topic=topic,
        adapter_family=None, deadline=__import__("datetime").datetime(2026, 11, 14))
    assert "openlabs-paper-readability/SKILL.md" in text and "story-review" in text
    assert "narrative-check" in text and "reader-check" in text
    assert (Path(owner.__file__).parents[3]
            / "workflows/paper/skills/openlabs-paper-readability/SKILL.md").is_file()
    note = owner._review_note({"review_outcome": {"status": "revise"}}, Path("/r.json"))
    assert "appendix" in note and "response letter" in note and "narrative-check" in note


def test_runner_logs_under_results_and_runtime_dirs_stay_put(tmp_path) -> None:
    # 2026-11-14: the Stop hook moved the lab runner's own agent-stdout.log,
    # agent-stderr.log and worker.log (results/<task>/attempts/<attempt>/) and
    # .openlabs/live-runtime/agent-stdout.log into staging while they were still
    # being written; their hash changed after registration and 26 seats were refused.
    context, paths = _context(tmp_path, {"status": "continuing"})
    ws, stage = paths["ws"], paths["stage"]
    runner_dir = ws / "results" / "owner-x" / "attempts" / "a1"
    runner_dir.mkdir(parents=True)
    for name in ("agent-stdout.log", "agent-stderr.log", "worker.log"):
        (runner_dir / name).write_text("running\n")
    (ws / ".openlabs" / "live-runtime").mkdir(parents=True)
    (ws / ".openlabs" / "live-runtime" / "agent-stdout.log").write_text("running\n")
    (ws / "solve.log").write_text("chain\n")                       # a stray log still moves
    owner.hook_normalize(context)
    assert all((runner_dir / name).is_file()
               for name in ("agent-stdout.log", "agent-stderr.log", "worker.log"))
    assert (ws / ".openlabs" / "live-runtime" / "agent-stdout.log").is_file()
    assert [p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()] == [
        "workspace/solve.log"]


def test_staged_files_with_equal_bytes_are_each_declared(tmp_path) -> None:
    # 2026-11-14 (0d957243): an empty staged log got the id staged-e3b0c442... which an
    # artifact cited from an earlier attempt already used; it was skipped, left
    # undeclared, and the commit refused the seat.
    context, paths = _context(tmp_path, {})
    stage = paths["stage"]
    (stage / "a.log").write_text("")
    (stage / "b.log").write_text("")
    earlier = {"artifact_id": "staged-e3b0c44298fc1c14", "kind": "data",
               "uri": (tmp_path / "earlier.log").resolve().as_uri(),
               "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
    (tmp_path / "earlier.log").write_text("")
    full = {**EXPECTED, "status": "completed", "summary": "s", "artifacts": [earlier],
            "claims": [], "next_actions": [], "paper_candidate": False}
    atomic_write_json(paths["result"], full)
    owner.hook_normalize(context)
    stored = json.loads(paths["result"].read_text())
    ids = [item["artifact_id"] for item in stored["artifacts"]]
    assert len(ids) == len(set(ids)) == 3
    uris = {item["uri"] for item in stored["artifacts"]}
    assert {(stage / n).resolve().as_uri() for n in ("a.log", "b.log")} <= uris
    assert validate_result_bundle(stored).valid


def test_settle_freezes_staged_files_and_corrects_only_their_hashes(tmp_path) -> None:
    from openlabs.contracts import sha256_file

    stage = tmp_path / "stage"
    stage.mkdir()
    log = stage / "OWNER_LOG.copy.md"
    log.write_text("step 1\n")
    declared = sha256_file(log)
    writer = log.open("a")                       # a process still writing the log
    writer.write("step 2\n")
    writer.flush()
    live = tmp_path / "committed.json"
    live.write_text("{}\n")
    payload = {"artifacts": [
        {"artifact_id": "log", "uri": log.resolve().as_uri(), "sha256": declared},
        {"artifact_id": "live", "uri": live.resolve().as_uri(), "sha256": "0" * 64},
    ]}
    settled, corrections = owner.settle_staged_artifacts(payload, stage)
    actual = sha256_file(log)
    assert actual != declared
    assert corrections == [{"artifact_id": "log", "path": "OWNER_LOG.copy.md",
                            "declared": declared, "actual": actual}]
    assert settled["artifacts"][0]["sha256"] == actual
    assert settled["artifacts"][1]["sha256"] == "0" * 64      # outside staging: untouched
    writer.write("step 3\n")                     # the old inode, not the frozen copy
    writer.close()
    assert sha256_file(log) == actual
    assert not [p for p in stage.iterdir() if p.name != log.name]   # no temp file left
    assert owner.settle_staged_artifacts(settled, stage)[1] == []


def test_owner_seat_with_a_grown_staged_log_is_committed_not_refused(tmp_path, monkeypatch):
    from openlabs.attempts import prepare_attempt_workspace
    from openlabs.contracts import RECEIPT_SCHEMA, sha256_file
    from test_owner_mode import _first_seat, _owner_program
    from test_research_program_flow import _tick

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    attempt_id = str(seat["current_attempt_id"])
    workspace = prepare_attempt_workspace(paths, seat, db.campaign(seat["campaign_id"]))
    log = workspace.artifact_staging_root / "solver" / "run.log"
    log.parent.mkdir(parents=True)
    log.write_text("iteration 1\n")
    declared = sha256_file(log)
    log.write_text("iteration 1\niteration 2\n")          # grew after the owner hashed it
    output = workspace.campaign_root / "results" / "seat" / "result.json"
    db.bind_attempt_spec(seat["task_id"], attempt_id=attempt_id, lab_id="ai",
                         output_path=str(output))
    db.mark_running(seat["task_id"], attempt_id=attempt_id, owner="test", pid=1,
                    lease_seconds=600)
    atomic_write_json(output, {"status": "continuing", "summary": "chain advanced",
                               "artifacts": [{"uri": str(log), "sha256": declared}]})
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
              if e["event_type"] == "staged_artifact_hash_corrected"]
    assert len(events) == 1


def test_brief_names_a_durable_campaign_data_dir(tmp_path, monkeypatch) -> None:
    # NC trial 2026-11-25: bridge downloads into the staging root failed (ENOENT on the
    # .download.part file) once the seat yielded and its staging root was removed.
    from test_owner_mode import _latest, _owner_program, _spec

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _latest(db, topic["campaign_id"])
    campaign = db.campaign(topic["campaign_id"])
    block = owner.spec_block(paths, settings, task=seat, spec=_spec(tmp_path, seat["task_id"]),
                             campaign=campaign, wall_seconds=14_400, db=db)
    body, footer = block["request"].split("\n---\n", 1)
    durable = owner.campaign_data_dir(paths, topic["campaign_id"])
    assert "kept across seats" in body and str(durable) not in body  # static part stays static
    assert str(durable) in footer and durable.is_dir()
    assert durable.parent == paths.instance_artifacts / "campaign-data"
    # One root for the seat's large files (2026-11-26): the footer no longer offers staging.
    assert "large outputs" not in footer and "artifact-stage" not in footer
    assert block["campaign_data_root"] == str(durable)


def test_new_declared_campaign_data_files_are_frozen_into_staging(tmp_path) -> None:
    import os

    from openlabs.contracts import sha256_file

    store = tmp_path / "artifacts"
    stage = store / "attempt" / "artifact-stage"
    stage.mkdir(parents=True)
    data = store / "instances" / "x" / "campaign-data" / "topic-1"
    data.mkdir(parents=True)
    new = data / "chains" / "run.npz"
    new.parent.mkdir()
    new.write_bytes(b"chain")
    old = data / "download.csv"
    old.write_text("a,b\n")
    os.utime(old, (1_000, 1_000))                    # written before this attempt began
    workspace = store / "attempt" / "campaign"
    workspace.mkdir()
    note = workspace / "note.json"
    note.write_text("{}\n")
    payload = {"artifacts": [
        {"artifact_id": "chain", "uri": new.as_uri(), "sha256": sha256_file(new)},
        {"artifact_id": "data", "uri": old.as_uri(), "sha256": sha256_file(old)},
        {"artifact_id": "note", "uri": note.as_uri(), "sha256": sha256_file(note)},
    ]}
    settled, corrections = owner.settle_staged_artifacts(
        payload, stage, live_root=store, started=2_000, keep=(workspace,))
    chain, data_entry, note_entry = settled["artifacts"]
    staged = Path(chain["uri"].removeprefix("file://"))
    assert staged.is_relative_to(stage.resolve()) and staged.read_bytes() == b"chain"
    assert new.is_file()                             # the original stays for later seats
    assert data_entry["uri"] == old.as_uri()         # cited, not produced: left alone
    assert note_entry["uri"] == note.as_uri()        # campaign workspace: left alone
    assert corrections == []
    # Without a live root nothing outside staging moves (the old behaviour).
    assert owner.settle_staged_artifacts(payload, stage)[0]["artifacts"][0]["uri"] == new.as_uri()


def test_owner_seat_citing_a_new_campaign_data_file_is_committed(tmp_path, monkeypatch):
    # Before 2026-11-26 the commit refused it: "new artifact must use attempt staging, not a
    # live artifact path" (14 attempts 2026-11-14..25).
    from openlabs.attempts import prepare_attempt_workspace
    from openlabs.contracts import RECEIPT_SCHEMA, sha256_file
    from test_owner_mode import _first_seat, _owner_program
    from test_research_program_flow import _tick

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    attempt_id = str(seat["current_attempt_id"])
    workspace = prepare_attempt_workspace(paths, seat, db.campaign(seat["campaign_id"]))
    chain = owner.campaign_data_dir(paths, topic["campaign_id"]) / "chains" / "run.npz"
    chain.parent.mkdir(parents=True)
    chain.write_bytes(b"posterior draws")
    output = workspace.campaign_root / "results" / "seat" / "result.json"
    db.bind_attempt_spec(seat["task_id"], attempt_id=attempt_id, lab_id="ai",
                         output_path=str(output))
    db.mark_running(seat["task_id"], attempt_id=attempt_id, owner="test", pid=1,
                    lease_seconds=600)
    atomic_write_json(output, {"status": "continuing", "summary": "chain advanced",
                               "artifacts": [{"uri": str(chain),
                                              "sha256": sha256_file(chain)}]})
    atomic_write_json(paths.result_inbox / f"{attempt_id}.json", {
        "schema_version": RECEIPT_SCHEMA, "task_id": seat["task_id"],
        "attempt_id": attempt_id, "campaign_id": seat["campaign_id"], "lab_id": "ai",
        "domain": seat["domain"], "agent_role": seat["agent_role"],
        "result_path": str(output), "sha256": sha256_file(output),
        "runtime": {"duration_seconds": 10.0, "exit_code": 0, "runner": seat["runner"],
                    "session_id": "s1"}})
    _tick(paths, settings, monkeypatch)
    assert db.task(seat["task_id"])["status"] == "succeeded", db.task(seat["task_id"])
    assert chain.read_bytes() == b"posterior draws"   # still there for the next seat
