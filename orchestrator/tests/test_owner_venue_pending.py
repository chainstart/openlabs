"""An owner seat that stops over unreadable venue evidence continues instead of a human stop.

2026-11-19/20: eight owner seats of four topics returned blocked_human because a publisher
refused the page with a journal's CAS 2025 zone or its charges (HTTP 403/406); each became
needs_human and a direction decision. Now the seat continues with the journal pending
verification (registry/verified-venues.yaml) or a verified alternative, at most
VENUE_PENDING_LIMIT times per topic.
"""

from __future__ import annotations

import json
from pathlib import Path

from openlabs import owner
from openlabs.config import OWNER_TASK_TYPE, OwnerSettings
from test_owner_mode import _first_seat, _latest, _owner_program, _seat_packet
from test_research_program_flow import _tick

ENERGY_POLICY = ("Energy Policy registration requires current journal-specific confirmation of "
                 "no mandatory page or submission charge. The publisher guide returned HTTP 403 "
                 "and the portal returned HTTP 406.")


def _stored(db, task_id) -> dict:
    return json.loads(Path(db.task(task_id)["result_path"]).read_text())


def test_venue_evidence_refusal_continues_with_instructions_then_stops_after_the_limit(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(session_max_seats=0))
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    for conversion in range(1, owner.VENUE_PENDING_LIMIT + 1):
        _seat_packet(db, paths, seat["task_id"], {"status": "blocked_human",
                                                  "reason": ENERGY_POLICY},
                     session="s1", artifact=True)
        report = _tick(paths, settings, monkeypatch)
        assert report.errors == [], report.errors
        assert db.task(seat["task_id"])["status"] == "succeeded"
        stored = _stored(db, seat["task_id"])
        assert stored["status"] == "completed" and "human_intervention" not in stored
        packet = stored["owner_packet"]
        assert packet["status"] == "continuing"
        assert packet["venue_pending_verification"]["conversion"] == conversion
        nxt = _latest(db, topic["campaign_id"])
        assert nxt["task_type"] == OWNER_TASK_TYPE and nxt["routing_reason"] == (
            owner.ROUTING_CONTINUE)
        note = json.loads(Path(nxt["input_path"]).read_text())["owner_packet"]["resume_note"]
        assert "venue mark-pending" in note and "venue alternatives" in note
        seat = _first_seat(paths, db, settings, monkeypatch, topic)
    # Past the limit the ordinary path applies: needs_human (direction decision).
    _seat_packet(db, paths, seat["task_id"], {"status": "blocked_human", "reason": ENERGY_POLICY},
                 session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert db.task(seat["task_id"])["status"] == "needs_human"
    assert db.count_events("campaign", topic["campaign_id"], owner.VENUE_PENDING_EVENT) == (
        owner.VENUE_PENDING_LIMIT)


def test_other_human_stops_are_left_alone(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(
        tmp_path, monkeypatch, owner_settings=OwnerSettings(session_max_seats=0))
    seat = _first_seat(paths, db, settings, monkeypatch, topic)
    # A reference paper behind a 403 is not venue evidence (topic-d9479445, 2026-11-19).
    _seat_packet(db, paths, seat["task_id"], {
        "status": "blocked_human",
        "reason": "The body of Elliot (2026, SSRN 7615054) is unreadable (HTTP 403); a readable "
                  "copy is required before the decisive analysis."}, session="s1", artifact=True)
    _tick(paths, settings, monkeypatch)
    assert db.task(seat["task_id"])["status"] == "needs_human"
    assert db.count_events("campaign", topic["campaign_id"], owner.VENUE_PENDING_EVENT) == 0


def test_venue_access_block_reads_the_packet_and_the_flag() -> None:
    def bundle(reason, **packet):
        return {"status": "needs_human", "human_intervention": {"reason": reason},
                "owner_packet": {"status": "blocked_human", "reason": reason, **packet}}

    assert owner.venue_access_block(bundle(ENERGY_POLICY))
    assert owner.venue_access_block(bundle(
        "中科院 2025 分区 evidence: fenqubiao returned 403"))
    assert owner.venue_access_block(bundle("need a person", venue_pending_verification=True))
    assert owner.venue_access_block(bundle("MAST is down")) is None
    assert owner.venue_access_block(bundle("the journal fit is weak")) is None
    assert owner.venue_access_block({"status": "completed", "owner_packet": {
        "status": "continuing", "reason": ENERGY_POLICY}}) is None
