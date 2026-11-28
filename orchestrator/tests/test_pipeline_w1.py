"""Pipeline overhaul W1 (2026-11-20): line-level shared facts and simplified supply config."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import test_research_lines as lines_tests
import test_research_program_flow as flow
from openlabs import engine, line_facts
from openlabs.config import OWNER_TASK_TYPE, SupplySettings, load_program_settings
from openlabs.program import open_topic_ledger
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet
from test_program_autonomy import _analysis_decision, _decide, _direction_tasks, _topic
from test_remote_wait import _job, queue  # noqa: F401 - pytest fixture
from test_research_program_flow import _tick

JOB = "9fe82e22248d4c05b603128efb6b1368"


# --------------------------------------------------------------------------- config


def test_supply_settings_defaults_and_overrides() -> None:
    supply = load_program_settings({}).supply
    assert supply == SupplySettings()
    assert supply.max_concurrent_scouts == 2
    assert supply.candidate_pool_size == 4
    assert supply.max_concurrent_reviews == 4
    parsed = load_program_settings({"supply": {
        "max_concurrent_scouts": 3, "scout_min_interval_hours": 0.5,
        "scout_weekly_usd_per_line": 120, "max_topic_data_gb": 1000,
        "dedup_similarity": 0.75, "max_concurrent_reviews": 2,
    }}).supply
    assert parsed.max_concurrent_scouts == 3 and parsed.scout_min_interval_hours == 0.5
    assert parsed.scout_weekly_usd_per_line == 120.0 and parsed.max_topic_data_gb == 1000.0
    assert parsed.dedup_similarity == 0.75 and parsed.max_concurrent_reviews == 2


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
    omission = {"gate_result": {"line_reference": {"id": "missing_card_capability"}}}
    assert line_facts.shared_reference(paths, settings, topic=topic, payload=omission,
                                       classification={"items": []}, artifacts=[]) is None
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
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    # Pre-fill the per-topic reference wait count to the built-in limit (2).
    db.update_meta({line_facts.REFERENCE_WAIT_PREFIX + topic["topic_id"]: "2"})
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


def test_a_clear_own_failure_still_freezes(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    clear = [{"name": "E1", "delta": 0.5, "tolerance": 0.1, "uncertainty": 0.01}]
    _seat_packet(db, paths, seat["task_id"], _freeze_packet(failed_criteria=clear),
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


def test_changed_reference_receipt_is_not_the_same_shared_failure():
    record = {"reference_id": "control", "receipt_sha256": "old"}
    assert not line_facts._same_reference(record, {"id": "control", "receipt_sha256": "new"})
