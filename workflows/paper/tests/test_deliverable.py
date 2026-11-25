"""B5 (2026-11-25): one deliverability verdict, one "delivered", one default submitter."""

import json

import pytest

from paper_writing import deliverable, program_delivery


def test_stage_table_states_every_stage_for_each_check():
    for row in deliverable.STAGE_EFFECTS:
        assert {"check", "review", "presentation", "delivery", "why"} <= set(row)
        assert all(str(row[key]).strip() for key in row)


def test_summarize_is_the_verdict():
    status = {"paper_id": "p", "version": "1.0", "frozen": None, "delivered": False,
              "review": {"ready": True, "current": True, "decision_current": True,
                         "review_mode": "presentation"}, "issues": []}
    verdict = deliverable.summarize(status)
    assert verdict["deliverable"] is True and verdict["review_mode"] == "presentation"
    status["issues"] = [{"code": "SCHEMATIC-ROUTE-NOT-VECTOR", "remedy": "writer",
                         "source": "delivery_floor", "message": "x"}]
    verdict = deliverable.summarize(status)
    assert verdict["deliverable"] is False
    assert verdict["issues"][0]["stage_check"] == "schematic route"
    assert deliverable.summarize({**status, "issues": [], "frozen": "frozen"})["deliverable"] is False


def test_delivered_needs_the_block_for_the_current_version_and_its_receipt(tmp_path):
    record = {"version": "1.2", "delivery": {"package_id": "pkg-a", "version": "1.2"}}
    assert deliverable.delivered(record, tmp_path, "p") is False
    folder = tmp_path / "papers" / "p" / "releases"
    folder.mkdir(parents=True)
    (folder / "pkg_a.json").write_text(json.dumps({"paper_id": "p", "package_id": "pkg-a"}))
    assert deliverable.delivered(record, tmp_path, "p") is True
    assert deliverable.delivered({**record, "version": "1.3"}, tmp_path, "p") is False


def test_registry_ready_and_second_author():
    assert deliverable.registry_ready(None, {"version": "1"}) == []
    assert deliverable.registry_ready({"writing_release": {"status": "ready"}, "version": "2"},
                                      {"version": "1"}) == [
        "registry version 2 is not the delivered 1 (revision in progress)"]
    roster = [{"name": "A"}, {"name": "B"}]
    assert deliverable.second_author(None, roster) == ({"name": "B"}, "default_roster_second_author")
    paper = {"authors": {"people": [{"name": "C"}, {"name": "D"}]}}
    assert deliverable.second_author(paper, roster) == ({"name": "D"}, "byline_second_author")
    assert deliverable.second_author({"authors": [{"name": "C"}]}, [{"name": "A"}]) is None


def test_default_handler_is_the_papers_second_author(tmp_path, monkeypatch):
    roster = [{"name": "A", "email": "a@x"}, {"name": "B", "email": "b@x"},
              {"name": "D", "email": "d@x"}]
    monkeypatch.setattr(program_delivery, "load_registry_settings",
                        lambda root: {"defaults": {"authors": roster}})
    assert program_delivery.default_handler(tmp_path) == {"name": "B", "email": "b@x"}
    paper = {"authors": {"people": [{"name": "A"}, {"name": "D"}]}}
    # The byline's second author; the email comes from the roster entry of the same name.
    assert program_delivery.default_handler(tmp_path, paper=paper) == {"name": "D", "email": "d@x"}
    # No address for the byline's second author: the roster's second author.
    assert program_delivery.default_handler(
        tmp_path, paper={"authors": [{"name": "A"}, {"name": "Z"}]}) == {"name": "B", "email": "b@x"}
    monkeypatch.setattr(program_delivery, "load_registry_settings",
                        lambda root: {"defaults": {"authors": roster[:1]}})
    with pytest.raises(program_delivery.ProgramDeliveryError):
        program_delivery.default_handler(tmp_path)
