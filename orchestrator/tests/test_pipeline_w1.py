"""Pipeline overhaul W1 (2026-11-20): line-level shared facts, intake screens, the pilot
gate, target memory and scout backoff."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import test_idle_spin as idle
import test_owner_recompute as recompute
import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs import engine, line_facts, program_flow, supply_screen
from openlabs.config import OWNER_TASK_TYPE, SupplySettings, load_program_settings
from openlabs.program import open_topic_ledger
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet
from test_program_autonomy import _analysis_decision, _decide, _direction_tasks, _topic
from test_remote_wait import _job, queue  # noqa: F401 - pytest fixture
from test_research_program_flow import _tick

JOB = "9fe82e22248d4c05b603128efb6b1368"


# --------------------------------------------------------------------------- config


def test_supply_settings_default_on_and_overridable() -> None:
    supply = load_program_settings({}).supply
    assert supply == SupplySettings()
    assert supply.line_facts and supply.pilot and supply.target_memory
    assert supply.borderline_relative_margin == 0.05 and supply.pilot_max_threads == 8
    parsed = load_program_settings({"supply": {
        "line_facts": False, "pilot_max_threads": 28, "pilot_core_hours_max": 6,
        "borderline_relative_margin": 0.1}}).supply
    assert not parsed.line_facts and parsed.pilot_max_threads == 8  # never above 8 threads
    assert parsed.pilot_core_hours_max == 6 and parsed.borderline_relative_margin == 0.1


def test_repository_config_documents_the_supply_table() -> None:
    import tomllib

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "config" / "openlabs.toml").read_text(encoding="utf-8"))
    assert load_program_settings(config["program"]).supply == SupplySettings()


# --------------------------------------------------------------------------- criteria


def _verdict_artifact(tmp_path: Path, *, plus: float | None = 1.548,
                      minus: float | None = 1.0985, delta: float = 2.0083775638287307) -> Path:
    item = {"published": 83.11, "ours_median": 85.118, "delta": delta, "tolerance_abs": 2.0,
            "pass_tolerance": False}
    if plus is not None:
        item["ours_plus"] = plus
    if minus is not None:
        item["ours_minus"] = minus
    path = tmp_path / "control_verdict.json"
    path.write_text(json.dumps({"source_job": JOB, "comparison": {
        "incl": item,
        "q": {"delta": 0.0066, "tolerance_abs": 0.0135, "pass_tolerance": True}}}))
    return path


def _payload(path: Path, **extra) -> dict:
    return {"summary": "Control inclination misses the 2 degree tolerance.",
            "artifacts": [{"artifact_id": "control-verdict", "uri": f"file://{path}"},
                          {"artifact_id": "unrelated", "uri": f"file://{path}.other.json"}],
            "gate_result": {"promotion_decision": "freeze",
                            "freeze_reason_class": "feasibility_precheck_failed",
                            "evidence": ["control-verdict"]}, **extra}


def test_miss_below_the_measurement_uncertainty_is_borderline(tmp_path) -> None:
    payload = _payload(_verdict_artifact(tmp_path))
    result = line_facts.classify(line_facts.criteria_of(payload), 0.05)
    assert result["verdict"] == "borderline"
    (item,) = result["items"]
    assert item["name"] == "incl" and abs(item["excess"] - 0.00838) < 1e-4
    # delta > 0: the error toward the tolerance is the lower one.
    assert item["uncertainty"] == 1.0985 and item["basis"] == "measurement_uncertainty"


def test_without_uncertainty_the_relative_margin_decides(tmp_path) -> None:
    payload = _payload(_verdict_artifact(tmp_path, plus=None, minus=None))
    assert line_facts.classify(line_facts.criteria_of(payload), 0.05)["verdict"] == "borderline"
    wide = _payload(_verdict_artifact(tmp_path, plus=None, minus=None, delta=2.5))
    result = line_facts.classify(line_facts.criteria_of(wide), 0.05)
    assert result["verdict"] == "failed" and result["items"][0]["basis"] == "relative_margin_0.05"
    # A miss far beyond its uncertainty is a clear failure.
    clear = _payload(_verdict_artifact(tmp_path, plus=0.1, minus=0.1, delta=2.5))
    assert line_facts.classify(line_facts.criteria_of(clear), 0.05)["verdict"] == "failed"


def test_declared_criteria_and_stated_misses_are_read() -> None:
    declared = {"gate_result": {"failed_criteria": [
        {"name": "E1 half-width", "value": 0.104, "limit": 0.10, "uncertainty": 0.01}]}}
    assert line_facts.classify(line_facts.criteria_of(declared), 0.05)["verdict"] == "borderline"
    text = {"summary": "Frozen: control inclination difference 2.00837756 degrees exceeds "
                       "2 degrees.", "gate_result": {}}
    (item,) = line_facts.criteria_of(text)
    assert item["source"] == "text" and abs(item["excess"] - 0.00837756) < 1e-9
    assert line_facts.classify([item], 0.05)["verdict"] == "borderline"
    assert line_facts.classify([], 0.05)["verdict"] == "none"


def _receipt_line(paths, tmp_path: Path) -> Path:
    receipt = tmp_path / "CONTROL_RECEIPT.json"
    receipt.write_text(json.dumps({"tag": "TIC55522736", "job_id": "b" * 32,
                                   "all_job_ids": ["b" * 32, "c" * 32]}))
    path = paths.data / "registry" / "research-lines.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "      sop: sop.md\n",
        "      sop: sop.md\n      standard_solver:\n"
        f"        control_receipt: {receipt}\n"), encoding="utf-8")
    return receipt


def test_the_lines_control_receipt_is_found_by_job_or_tag(tmp_path) -> None:
    paths, _db, settings = lines_tests._line_setup(tmp_path, "ready")
    _receipt_line(paths, tmp_path)
    (reference,) = line_facts.line_references(paths, settings, lines_tests.LINE)
    assert reference["job_ids"] == ["b" * 32, "c" * 32]
    assert "TIC 55522736" in reference["aliases"]
    topic = {"topic_id": "topic-x", "research_line": lines_tests.LINE}
    by_tag = {"summary": "The TIC 55522736 control misses its tolerance.", "gate_result": {}}
    found = line_facts.shared_reference(paths, settings, topic=topic, payload=by_tag,
                                        classification={"items": []}, artifacts=[])
    assert found and found["source"] == "line_reference" and found["receipt_sha256"]
    own = {"summary": "The target's own q profile is open.", "gate_result": {}}
    assert line_facts.shared_reference(paths, settings, topic=topic, payload=own,
                                       classification={"items": []}, artifacts=[]) is None
    # A job another topic of the line cites in its recorded results is shared too.
    other = tmp_path / "other" / "result.json"
    other.parent.mkdir()
    other.write_text(json.dumps({"remote_compute": {"job_id": JOB}}))
    ledger = {"topics": [{"topic_id": "topic-y", "research_line": lines_tests.LINE,
                          "freeze_evidence": [{"path": str(other), "sha256": "0" * 64}]}]}
    by_job = {"summary": f"Control job {JOB} misses.", "gate_result": {}}
    found = line_facts.shared_reference(paths, settings, topic=topic, payload=by_job,
                                        classification={"items": []}, artifacts=[],
                                        ledger_document=ledger)
    assert found and found["source"] == "cross_topic" and found["job_ids"] == [JOB]


# --------------------------------------------------------------------------- owner flow


def _set_line(paths, settings, topic_ids, line: str = "astro-test") -> None:
    ledger = open_topic_ledger(paths, settings.program)
    with ledger.transaction() as document:
        for topic in document["topics"]:
            if topic["topic_id"] in topic_ids:
                topic["research_line"] = line


def _freeze_packet(**extra) -> dict:
    return {"status": "frozen", "freeze_reason_class": "feasibility_precheck_failed",
            "reason": "The control inclination misses the 2 degree tolerance.", **extra}


BORDERLINE = [{"name": "control inclination", "delta": 2.008, "tolerance": 2.0,
               "uncertainty": 1.1}]


def test_a_freeze_while_a_named_job_is_queued_parks_on_it(tmp_path, monkeypatch, queue):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    _job(queue, JOB, "queued")
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], _freeze_packet(
        remote_compute={"job_id": JOB, "state_at_gate": "queued"}), session="s1",
        artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"
    parked = _latest(db, topic["campaign_id"])
    assert parked["status"] == "awaiting_remote" and parked["task_id"].startswith("await:")
    assert "did not apply the feasibility-precheck freeze" in parked["objective"]
    kinds = [entry.get("kind") for entry in _topic(paths, settings, topic["topic_id"])["history"]]
    assert "freeze_deferred_job_pending" in kinds
    assert db.meta_get(line_facts.REFERENCE_WAIT_PREFIX + topic["topic_id"]) == "1"


def test_the_job_wait_is_bounded_and_a_finished_job_does_not_park(tmp_path, monkeypatch, queue):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, supply=SupplySettings(reference_wait_max=0))
    _job(queue, JOB, "queued")
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], _freeze_packet(
        remote_compute={"job_id": JOB}), session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"


def test_a_borderline_own_miss_goes_to_a_direction_decision(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], _freeze_packet(failed_criteria=BORDERLINE),
                 session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert _topic(paths, settings, topic["topic_id"])["status"] == "active"
    (task,) = _direction_tasks(db)
    packet = json.loads(Path(task["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == line_facts.TRIGGER_BORDERLINE
    assert any("borderline" in reason for reason in packet["reasons_to_answer"])


def test_a_clear_own_failure_and_the_switch_off_still_freeze(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    clear = [{"name": "E1", "delta": 0.5, "tolerance": 0.1, "uncertainty": 0.01}]
    _seat_packet(db, paths, seat["task_id"], _freeze_packet(failed_criteria=clear),
                 session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"
    paths, db, settings, (topic,) = _owner_program(
        tmp_path / "off", monkeypatch, supply=SupplySettings(line_facts=False))
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    _seat_packet(db, paths, seat["task_id"], _freeze_packet(failed_criteria=BORDERLINE),
                 session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"


def _shared(**extra) -> dict:
    return _freeze_packet(failed_criteria=BORDERLINE,
                          line_reference={"id": "control-TIC55522736", "job_id": JOB}, **extra)


def _leased_first(db, topics):
    """The topic whose first seat holds the single test slot comes first."""

    return sorted(topics, key=lambda t: _latest(db, t["campaign_id"])["status"] != "leased")


def _wait_on_block(db, paths, settings, topic) -> str | None:
    """The second topic reports the same shared-reference failure (as its seat would)."""

    payload = {"summary": "Control inclination misses its tolerance.",
               "gate_result": {"promotion_decision": "freeze",
                               "freeze_reason_class": "feasibility_precheck_failed",
                               "failed_criteria": BORDERLINE,
                               "line_reference": {"id": "control-TIC55522736", "job_id": JOB}}}
    current = _topic(paths, settings, topic["topic_id"])
    return line_facts.intercept_precheck_freeze(
        db, paths, settings, engine.TickReport(), topic=current,
        task={"task_id": f"seat-of-{topic['topic_id']}"}, payload=payload, evidence=[],
        reason_class="feasibility_precheck_failed")


def test_a_shared_reference_blocks_the_line_and_later_topics_wait(tmp_path, monkeypatch):
    paths, db, settings, topics = _owner_program(tmp_path, monkeypatch, cards=2)
    first, second = _leased_first(db, topics)
    _set_line(paths, settings, {first["topic_id"], second["topic_id"]})
    seat = _first_seat(paths, db, settings, monkeypatch, first)
    _seat_packet(db, paths, seat["task_id"], _shared(), session="s1", artifact=True)
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    assert _topic(paths, settings, first["topic_id"])["status"] == "active"
    block = line_facts.block_of(db, "astro-test")
    assert block["state"] == "decision_pending" and block["topic_id"] == first["topic_id"]
    assert block["reason"] == "reference_borderline"
    assert program_flow.lines_not_ready(paths, settings, ["astro-test"], db=db) == {
        "astro-test": "line_blocked:reference_borderline"}
    (decision,) = _direction_tasks(db)
    packet = json.loads(Path(decision["input_path"]).read_text(encoding="utf-8"))
    assert packet["trigger"]["reason"] == line_facts.TRIGGER_LINE_REFERENCE
    assert any("shared reference" in reason for reason in packet["reasons_to_answer"])

    # The other topic fails against the same reference: it waits, no decision, no freeze.
    assert _wait_on_block(db, paths, settings, second) == "handled"
    assert _topic(paths, settings, second["topic_id"])["status"] == "active"
    assert len(_direction_tasks(db)) == 1
    assert line_facts.campaign_waiting(db, second["campaign_id"])
    from openlabs import program_autonomy

    assert program_autonomy.campaign_on_hold(db, settings, second["campaign_id"])
    assert program_autonomy.hold_reason(db, settings, second["campaign_id"]) == "line_block_wait"
    report = _tick(paths, settings, monkeypatch)
    assert report.program["line_blocks"][0]["waiting_topics"] == [second["topic_id"]]

    # One targeted re-check of the reference; then the representative passes its precheck.
    reason = packet["reasons_to_answer"][0]
    report = _decide(paths, settings, monkeypatch, db, _analysis_decision(reason))
    assert line_facts.block_of(db, "astro-test")["state"] == "under_review"
    assert _latest(db, first["campaign_id"])["task_type"] == OWNER_TASK_TYPE
    # A seat that is still in its precheck does not release the block ...
    representative = _topic(paths, settings, first["topic_id"])
    assert not line_facts.on_progress(db, paths, settings, report, topic=representative,
                                      payload={"owner_packet": {"phase": "precheck"}})
    # ... one that reports progress past it does.
    report = engine.TickReport()
    assert line_facts.on_progress(db, paths, settings, report, topic=representative,
                                  payload={"owner_packet": {"status": "continuing",
                                                            "phase": "solving"}})
    assert line_facts.block_of(db, "astro-test") is None
    assert not line_facts.campaign_waiting(db, second["campaign_id"])
    assert report.program["line_blocks_released"][0]["released_topics"] == [second["topic_id"]]


def test_release_gives_an_idle_waiting_owner_topic_its_next_seat(tmp_path, monkeypatch):
    paths, db, settings, topics = _owner_program(tmp_path, monkeypatch, cards=2)
    first, second = _leased_first(db, topics)
    _set_line(paths, settings, {first["topic_id"], second["topic_id"]})
    seat = _first_seat(paths, db, settings, monkeypatch, first)
    _seat_packet(db, paths, seat["task_id"], _shared(), session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _wait_on_block(db, paths, settings, second) == "handled"
    # The waiting topic's queued seat is withdrawn (as after its own freeze request).
    queued = _latest(db, second["campaign_id"])
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='cancelled' WHERE campaign_id=?",
                           (second["campaign_id"],))
    entry = line_facts.release(db, paths, settings, None, line="astro-test",
                               reason="control re-run", by="manual:test")
    assert entry["released_topics"] == [second["topic_id"]]
    seat = _latest(db, second["campaign_id"])
    assert seat["task_id"] != queued["task_id"]
    assert seat["routing_reason"] == line_facts.ROUTING_RELEASED
    assert "was not applied" in seat["objective"]


def test_a_frozen_representative_confirms_the_block(tmp_path, monkeypatch):
    paths, db, settings, (first,) = _owner_program(tmp_path, monkeypatch)
    _set_line(paths, settings, {first["topic_id"]})
    seat = _first_seat(paths, db, settings, monkeypatch, first)
    _seat_packet(db, paths, seat["task_id"], _shared(), session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    (decision,) = _direction_tasks(db)
    packet = json.loads(Path(decision["input_path"]).read_text(encoding="utf-8"))
    report = _decide(paths, settings, monkeypatch, db, {
        "choice": "freeze", "rationale": "The control systematic is real.",
        "answers_reason": packet["reasons_to_answer"][0],
        "freeze": {"reason_class": "feasibility_precheck_failed", "reopen_conditions": [
            {"type": "new_method", "description": "A re-validated shared control."}]}})
    assert report.errors == [], report.errors
    assert _topic(paths, settings, first["topic_id"])["status"] == "frozen"
    assert line_facts.block_of(db, "astro-test")["state"] == "confirmed"
    entry = line_facts.release(db, paths, settings, None, line="astro-test",
                               reason="control re-run", by="manual:test")
    assert entry["released_topics"] == [] and line_facts.block_of(db, "astro-test") is None


def test_waits_expire_into_their_own_direction_decision(tmp_path, monkeypatch):
    paths, db, settings, topics = _owner_program(tmp_path, monkeypatch, cards=2)
    first, second = _leased_first(db, topics)
    _set_line(paths, settings, {first["topic_id"], second["topic_id"]})
    seat = _first_seat(paths, db, settings, monkeypatch, first)
    _seat_packet(db, paths, seat["task_id"], _shared(), session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert _wait_on_block(db, paths, settings, second) == "handled"
    record = line_facts.block_of(db, "astro-test")
    record["since"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    db.update_meta({line_facts.BLOCK_PREFIX + "astro-test": json.dumps(record)})
    line_facts.tick(db, paths, settings, engine.TickReport())
    assert not line_facts.campaign_waiting(db, second["campaign_id"])
    triggers = [json.loads(Path(task["input_path"]).read_text())["trigger"]["reason"]
                for task in _direction_tasks(db)]
    assert line_facts.TRIGGER_BLOCK_EXPIRED in triggers


# --------------------------------------------------------------------------- dry-run report


def test_line_reopen_report_lists_line_level_freezes_and_writes_nothing(tmp_path, monkeypatch):
    paths, db, settings = lines_tests._line_setup(tmp_path, "ready")
    _receipt_line(paths, tmp_path)
    artifact = _verdict_artifact(tmp_path)
    results = {}
    for name, body in {
        "borderline": _payload(artifact),
        "queued": {"summary": "The single mandatory control remains queued.",
                   "remote_compute": {"job_id": JOB, "state_at_gate": "queued"},
                   "gate_result": {}},
        "own": {"summary": "Target q profile open on the reference sector.", "gate_result": {}},
    }.items():
        path = tmp_path / name / "result.json"
        path.parent.mkdir()
        body = dict(body)
        if name == "borderline":
            body["summary"] = "TIC 55522736 control inclination misses the tolerance."
        path.write_text(json.dumps(body))
        results[name] = path
    ledger = open_topic_ledger(paths, settings.program)
    with ledger.transaction() as document:
        for name, path in results.items():
            document["topics"].append({
                "topic_id": f"topic-{name}", "status": "frozen", "research_line": lines_tests.LINE,
                "freeze_reason_class": "feasibility_precheck_failed",
                "frozen_at": "2026-11-14T06:51:09Z", "history": [],
                "freeze_evidence": [{"path": str(path), "sha256": "0" * 64}]})
    before = hashlib.sha256(ledger.path.read_bytes()).hexdigest()
    report = line_facts.reopen_report(paths, settings)
    assert hashlib.sha256(ledger.path.read_bytes()).hexdigest() == before
    rows = {row["topic_id"]: row for row in report["topics"]}
    assert rows["topic-borderline"]["category"] == "line_reference_borderline"
    assert rows["topic-queued"]["category"] == "reference_queued_at_precheck_end"
    assert rows["topic-own"]["category"] == "topic_level" and not rows["topic-own"]["line_level"]
    assert report["dry_run"] is True and report["by_category"]["line_reference_borderline"] == 1


# --------------------------------------------------------------------------- intake screens


def _card(n: int = 0, **extra) -> dict:
    card = recompute._queued_card(n)
    card.update(extra)
    return card


def _caps_yaml(queue_path: Path | None = None) -> str:
    text = ("    capabilities:\n"
            "      third_light_prior: {available: true}\n"
            "      spot_model: {key: environment.standard_solver.spot_config}\n")
    return text


def test_a_card_needing_a_missing_capability_is_rejected(tmp_path, monkeypatch):
    card = _card(0, required_capabilities=["spot_model"])
    *_, outcome, topic = recompute._intake(tmp_path, monkeypatch, _caps_yaml(), card=card)
    assert outcome["status"] == "rejected" and outcome["reason"] == "card_capability_missing"
    assert "spot_model" in topic["card_errors"][0]
    assert topic["card_repair"]["status"] == "not_repairable"
    ok = _card(1, required_capabilities=["third_light_prior"])
    *_, outcome, _topic_ = recompute._intake(tmp_path / "b", monkeypatch, _caps_yaml(), card=ok)
    assert outcome["status"] == "proposed", outcome
    unknown = _card(2, required_capabilities=["flux_calibration"])
    *_, outcome, topic = recompute._intake(tmp_path / "c", monkeypatch, _caps_yaml(),
                                           card=unknown)
    assert outcome["reason"] == "card_capability_missing"
    assert "not in the line's capability table" in topic["card_errors"][0]


def test_capability_table_reading() -> None:
    entry = {"capabilities": {"a": True, "b": "unavailable", "c": {"status": "validated"},
                              "d": {"key": "environment.x"}},
             "environment": {"x": {"validated": False}}}
    assert supply_screen.capability_status(entry, "a")[0]
    assert not supply_screen.capability_status(entry, "b")[0]
    assert supply_screen.capability_status(entry, "c")[0]
    assert not supply_screen.capability_status(entry, "d")[0]
    assert not supply_screen.capability_status(entry, "environment.x")[0]


def _aemo_zip(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ("C,NEMP.WORLD,DVD_DISPATCHLOAD,AEMO,PUBLIC\n"
            "I,DISPATCH,UNIT_SOLUTION,5," + ",".join(columns) + "\n"
            "D,DISPATCH,UNIT_SOLUTION,5," + ",".join("1" for _ in columns) + "\n")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".CSV", body)


def test_data_requirements_check_column_coverage(tmp_path, monkeypatch):
    folder = tmp_path / "DISPATCHLOAD"
    for month in ("202101", "202102", "202103", "202104"):
        columns = ["SETTLEMENTDATE", "DUID"] + (["UIGF"] if month == "202104" else [])
        _aemo_zip(folder / f"{month}_FILE01_PUBLIC_DVD_DISPATCHLOAD_{month}010000.zip", columns)
    requirement = {"name": "UIGF", "glob": str(folder / "*.zip"), "columns": ["UIGF"],
                   "header": "aemo_mms"}
    card = _card(0, data_requirements=[requirement])
    *_, outcome, topic = recompute._intake(tmp_path, monkeypatch, "", card=card)
    assert outcome["reason"] == "card_data_unavailable"
    assert "1/4 files" in topic["card_errors"][0]
    coverage = topic["card_check"]["data_coverage"][0]
    assert coverage["files"] == 4 and coverage["covered"] == 1
    narrow = _card(1, data_requirements=[
        {**requirement, "months": {"from": "2021-04", "to": "2021-12"}}])
    *_, outcome, _ = recompute._intake(tmp_path / "b", monkeypatch, "", card=narrow)
    assert outcome["status"] == "proposed", outcome
    csv = tmp_path / "plain" / "a.csv"
    csv.parent.mkdir()
    csv.write_text("time,load\n1,2\n")
    assert supply_screen.file_columns(csv, "csv") == ["TIME", "LOAD"]


COUNTING_FAIL = (
    "import json, sys\nopen(%r, 'a').write('x')\n"
    "print(json.dumps({'verdict': 'fail', 'checks': [{'name': 'totality', 'pass': False, "
    "'hard': True, 'value': 0.3, 'rule': 'R_max >= 0.42'}]}))\nsys.exit(1)\n")


def test_a_target_that_failed_with_an_unchanged_entry_gets_no_new_card(tmp_path, monkeypatch):
    calls = tmp_path / "calls.txt"
    script = recompute._script(tmp_path, COUNTING_FAIL % str(calls))
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps({"candidates": [{"entry_id": "TIC441806604", "x": 1}]}))
    extra = recompute._precheck_yaml(script).replace(
        "          command:", f"          candidate_queue_unused: x\n          command:")
    paths, db, settings, outcome, topic = recompute._intake(tmp_path, monkeypatch, extra)
    assert outcome["reason"] == "card_precheck_failed" and calls.read_text() == "x"
    assert topic["card_check"]["target"] == "TIC441806604"
    from openlabs.program_flow import intake_card
    from openlabs.projects import load_project

    project = load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                           / "project.json")
    again = intake_card(db, paths, settings, project, recompute._queued_card(1),
                        decided_by="manual:t", provider="human", source_task_id=None,
                        receipt_digests=None)
    assert again["reason"] == "card_target_repeat_failure"
    assert calls.read_text() == "x"  # the precheck was not run again
    failed = supply_screen.failed_targets(open_topic_ledger(paths, settings.program).read(),
                                          lines_tests.LINE, {})
    assert failed == {"TIC441806604": "rejected:card_precheck_failed"}
    # Target memory off: the card is checked again.
    off = replace(settings, program=replace(settings.program, supply=SupplySettings(
        target_memory=False)))
    third = intake_card(db, paths, off, project, recompute._queued_card(2),
                        decided_by="manual:t", provider="human", source_task_id=None,
                        receipt_digests=None)
    assert third["reason"] == "card_precheck_failed" and calls.read_text() == "xx"


def test_entry_digest_change_lets_a_target_be_checked_again(tmp_path) -> None:
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps({"candidates": [{"entry_id": "TIC1", "metrics": 1,
                                                      "ledger_occupancy": {"state": "free"}}]}))
    digest = supply_screen.entry_digest(queue_file, "TIC1")
    document = {"topics": [{"topic_id": "topic-a", "research_line": "l", "status": "rejected",
                            "history": [{"to": "rejected", "reason": "card_precheck_failed",
                                         "at": "2099-01-01T00:00:00Z"}],
                            "card_check": {"target": "TIC1", "entry_digest": digest}}]}
    card = {"research_line": "l", "candidate_queue_entry": {"entry_id": "TIC1"}}
    template = {"candidate_queue": str(queue_file)}
    assert supply_screen.repeat_failure(document, card, template)
    # Only the occupancy changed: still the same input.
    queue_file.write_text(json.dumps({"candidates": [{"entry_id": "TIC1", "metrics": 1,
                                                      "ledger_occupancy": {"state": "x"}}]}))
    assert supply_screen.repeat_failure(document, card, template)
    queue_file.write_text(json.dumps({"candidates": [{"entry_id": "TIC1", "metrics": 2}]}))
    assert supply_screen.repeat_failure(document, card, template) is None
    frozen = {"topics": [{"topic_id": "topic-f", "research_line": "l", "status": "frozen",
                          "freeze_reason_class": "feasibility_precheck_failed", "history": [],
                          "card_check": {"target": "TIC1"}}]}
    assert "reopens" in supply_screen.repeat_failure(frozen, card, template)
    assert supply_screen.repeat_failure(frozen, {**card, "reopens": "topic-f"}, template) is None


# --------------------------------------------------------------------------- pilot gate


STAGE = ("import json, pathlib, sys\nout = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
         "out.mkdir(parents=True, exist_ok=True)\n"
         "(out / 'run.sh').write_text('echo pilot')\n"
         "print(json.dumps({'argv': ['bash', 'run.sh']}))\n")


def _pilot_yaml(tmp_path: Path, **spec) -> str:
    stage = tmp_path / "pilot_stage.py"
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text(STAGE)
    body = {"cpus": 12, "memory_mib": 4096, "timeout_seconds": 36000, "core_hours": 40,
            "verdict_file": "pilot.json", **spec}
    lines = "".join(f"          {key}: {value}\n" for key, value in body.items())
    return ("    admission_pilot:\n      per_template:\n        contact-binary-solution:\n"
            f"          stage: {sys.executable} {stage} {{entry_id}} --card {{card}} "
            "--out {out}\n" + lines)


def _finish_job(queue_root: Path, job_id: str, verdict: dict | None, state: str = "succeeded"):
    _job(queue_root, job_id, state, updated_at=datetime.now(UTC).isoformat())
    if verdict is not None:
        outputs = queue_root / "jobs" / job_id / "result" / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "pilot.json").write_text(json.dumps(verdict))


def test_the_pilot_runs_on_ailab_before_review_and_its_verdict_is_on_the_card(
        tmp_path, monkeypatch, queue):
    paths, db, settings, outcome, topic = recompute._intake(
        tmp_path, monkeypatch, _pilot_yaml(tmp_path / "s"),
        supply=SupplySettings(pilot_core_hours_max=16))
    assert outcome["status"] == "proposed", outcome
    pilot = topic["card_check"]["pilot"]
    # 12 threads asked: capped at 8; 40 core-hours asked: capped at 16 -> 2 h wall.
    assert pilot["status"] == "pending" and pilot["budget"]["cpus"] == 8
    assert pilot["budget"]["wall_seconds"] == 7200 and pilot["budget"]["core_hours_budget"] == 16
    engine._sync_active_projects(db, paths, settings, engine.TickReport())
    with db.connect() as connection:
        admission = dict(connection.execute(
            "SELECT * FROM campaigns WHERE campaign_id LIKE '%admission%' LIMIT 1").fetchone())
    schedule = program_flow.schedule_topic_admission(db, paths, settings, admission, epoch=1)
    assert schedule.task_id is None and schedule.reason == "admission_pilot_pending"
    submitted = []

    def fake_submit(source, argv, **kwargs):
        submitted.append((Path(source), argv, kwargs))
        job = "e" * 32
        _job(queue, job, "queued")
        return type("Submission", (), {"job_id": job})()

    (out,) = supply_screen.advance_pilots(db, paths, settings, engine.TickReport(),
                                          queue_root=queue, submit=fake_submit)
    assert out["status"] == "submitted" and out["cpus"] == 8
    source, argv, kwargs = submitted[0]
    assert (source / "run.sh").is_file() and argv == ["bash", "run.sh"]
    assert kwargs == {"cpu_threads": 8, "memory_mib": 4096, "wall_seconds": 7200}
    (out,) = supply_screen.advance_pilots(db, paths, settings, engine.TickReport(),
                                          queue_root=queue, submit=fake_submit)
    assert out["status"] == "running"
    _finish_job(queue, "e" * 32, {"verdict": "pass", "metrics": {"e1_half_width": 0.06}})
    (out,) = supply_screen.advance_pilots(db, paths, settings, engine.TickReport(),
                                          queue_root=queue, submit=fake_submit)
    assert out["status"] == "pass"
    card = open_topic_ledger(paths, settings.program).topic(topic["topic_id"])
    pilot = card["card_check"]["pilot"]
    assert pilot["verdict"] == "pass" and pilot["metrics"] == {"e1_half_width": 0.06}
    assert pilot["job_id"] == "e" * 32 and pilot["used_core_hours"] is not None
    schedule = program_flow.schedule_topic_admission(db, paths, settings, admission, epoch=1)
    assert schedule.task_id is not None


def test_a_failed_pilot_rejects_the_card_and_a_broken_one_retries(tmp_path, monkeypatch, queue):
    paths, db, settings, outcome, topic = recompute._intake(
        tmp_path, monkeypatch, _pilot_yaml(tmp_path / "s"))
    jobs = iter(["1" * 32, "2" * 32, "3" * 32])

    def fake_submit(source, argv, **kwargs):
        job = next(jobs)
        _job(queue, job, "queued")
        return job

    supply_screen.advance_pilots(db, paths, settings, engine.TickReport(), queue_root=queue,
                                 submit=fake_submit)
    _finish_job(queue, "1" * 32, None, state="failed")  # crashed: retried
    (out,) = supply_screen.advance_pilots(db, paths, settings, engine.TickReport(),
                                          queue_root=queue, submit=fake_submit)
    assert out["status"] == "submitted" and out["job_id"] == "2" * 32
    _finish_job(queue, "2" * 32, {"verdict": "fail", "reasons": ["E1 interval open"]})
    (out,) = supply_screen.advance_pilots(db, paths, settings, engine.TickReport(),
                                          queue_root=queue, submit=fake_submit)
    assert out["status"] == "fail"
    rejected = open_topic_ledger(paths, settings.program).topic(topic["topic_id"])
    assert rejected["status"] == "rejected"
    assert rejected["history"][-1]["reason"] == "card_pilot_failed"
    assert rejected["card_check"]["pilot"]["reasons"] == ["E1 interval open"]


# --------------------------------------------------------------------------- scouts


def test_no_scout_for_a_queue_with_nothing_drawable(tmp_path, monkeypatch):
    paths, queue_file = idle._queued_line(tmp_path)
    queue_file.write_text(json.dumps({"candidates": [
        {"entry_id": "TIC 1", "ledger_occupancy": {"state": "in_flight"}}]}))
    db = flow._db(paths)
    settings = flow._settings(scout_min_interval_hours=0)
    templates = program_flow.line_templates(
        program_flow.research_lines_document(paths, settings), lines_tests.LINE)
    if any("candidate_queue" not in item for item in templates):
        # Only a line whose every template is enumerated is judged by its queue.
        path = paths.data / "registry" / "research-lines.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("        minimum_content:", f"        candidate_queue: "
                                     f"{queue_file}\n        minimum_content:")
                        .replace(f"        candidate_queue: {queue_file}\n"
                                 f"        candidate_queue: {queue_file}\n",
                                 f"        candidate_queue: {queue_file}\n"),
                        encoding="utf-8")
    report = _tick(paths, settings, monkeypatch)
    assert report.program["scouts_scheduled"] == []
    assert report.program["scout_blocked"] == "candidate_queue_empty"
    (signal,) = report.program["line_supply"]
    assert signal["signal"] == "supply_exhausted" and signal["drawable"] == 0
    queue_file.write_text(json.dumps({"candidates": [{"entry_id": "TIC 2"}]}))
    report = _tick(paths, settings, monkeypatch)
    assert len(report.program["scouts_scheduled"]) == 1


def test_empty_draw_backoff_doubles_past_the_steps_up_to_the_cap(tmp_path, monkeypatch):
    paths, _queue = idle._queued_line(tmp_path)
    db = flow._db(paths)
    settings = flow._settings(scout_min_interval_hours=0, scout_exhausted_after=0,
                              scout_empty_backoff_hours=(1.0, 6.0))
    state = {"count": 4, "fingerprint": None, "last_at": datetime.now(UTC).isoformat(),
             "reason": "candidate_queue_exhausted"}
    projects = program_flow.program_projects(paths)
    document = open_topic_ledger(paths, settings.program).read()
    state["fingerprint"] = program_flow.scout_supply_fingerprint(paths, settings, projects[0],
                                                                 document)
    db.update_meta({program_flow.SCOUT_SUPPLY_PREFIX + lines_tests.LINE: json.dumps(state)})
    blocks = program_flow.scout_supply_blocks(db, paths, settings, projects, document,
                                              moment=datetime.now(UTC))
    assert blocks[lines_tests.LINE]["backoff_hours"] == 24.0  # 6 x 2 x 2
    state["count"] = 9
    db.update_meta({program_flow.SCOUT_SUPPLY_PREFIX + lines_tests.LINE: json.dumps(state)})
    blocks = program_flow.scout_supply_blocks(db, paths, settings, projects, document,
                                              moment=datetime.now(UTC))
    assert blocks[lines_tests.LINE]["backoff_hours"] == 48.0


def test_a_card_drawn_from_a_held_entry_waits_for_its_capability(tmp_path, monkeypatch):
    queue_file = tmp_path / "held-queue.json"
    tmp_path.mkdir(parents=True, exist_ok=True)
    queue_file.write_text(json.dumps({"candidates": [], "held_candidates": [
        {"entry_id": "TIC441806604", "draw_hold": {
            "reason": "needs_spot", "release_when": {
                "kind": "line_capability", "key": "environment.standard_solver.spot_config"}}}]}))
    entry = {"id": "l", "paper_templates": [], "environment": {"standard_solver": {}}}
    card = _card(0)
    card["research_line"] = "l"
    problems = supply_screen.capability_problems(
        None, None, card, entry, {"candidate_queue": str(queue_file)})
    assert problems and "needs_spot" in problems[0]
    entry["environment"]["standard_solver"]["spot_config"] = {"validated": True}
    assert supply_screen.capability_problems(
        None, None, card, entry, {"candidate_queue": str(queue_file)}) == []
