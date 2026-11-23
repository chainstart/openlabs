from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from openlabs import owner, paper_figures
from openlabs.config import RunnerSpec
from openlabs.contracts import atomic_write_json, sha256_file
from test_owner_mode import _latest, _owner_program


def _fixture(tmp_path, monkeypatch):
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    seat = _latest(db, topic["campaign_id"])
    runner = seat["runner"]
    settings = replace(settings, runners={
        runner: RunnerSpec(name=runner, provider="openai-codex", tier="lead", model="gpt"),
    })
    campaign_root = Path(db.campaign(topic["campaign_id"])["state_path"])
    manuscript = campaign_root / "papers" / "p" / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text("original")
    shared = paths.data / "papers" / "p" / "manuscript"
    shared.mkdir(parents=True)
    (shared / "main.tex").write_text("delivered")
    report = SimpleNamespace(enqueued=[], program={}, errors=[])
    return paths, db, settings, manuscript, report, seat


def test_missing_schematic_queues_worker_twice_then_owner(tmp_path, monkeypatch):
    paths, db, settings, manuscript, report, seat = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(paper_figures, "check", lambda *_: {
        "manuscript": str(manuscript), "blocking": [],
        "repair_required": [{"figure": "plan", "code": "FIG-SCHEMATIC-MISSING", "message": "Draw design."}],
    })
    result_path = tmp_path / "owner-result.json"
    args = {"task": seat, "packet": {"paper_id": "p", "request_figure_assistant": True}, "result_path": result_path}
    assert owner._enqueue_review(db, paths, settings, report, **args) is None
    first = db.task(report.enqueued[-1])
    assert first["task_type"] == paper_figures.TASK_TYPE
    assert first["runner"] == seat["runner"] and first["max_attempts"] == 1
    assert "rendered PNG" in first["objective"]
    owner._after_figure_repair(db, paths, settings, report, task=first, successful=False)
    second = db.task(report.enqueued[-1])
    assert second["task_type"] == paper_figures.TASK_TYPE and second["task_id"] != first["task_id"]
    owner._after_figure_repair(db, paths, settings, report, task=second, successful=False)
    recovery = db.task(report.enqueued[-1])
    assert owner.is_owner_task(recovery)
    assert "Draw design." in recovery["objective"]


def test_bound_repair_is_imported_and_original_writer_hands_off_review(tmp_path, monkeypatch):
    paths, db, settings, manuscript, report, seat = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(paper_figures, "check", lambda *_: {
        "manuscript": str(manuscript),
        "blocking": [] if (manuscript / "figures/design.pdf").is_file() else [
            {"figure": "design", "code": "FIG-NOT-BUILT", "message": "Build design."},
        ],
    })
    owner._enqueue_review(db, paths, settings, report, task=seat,
                          packet={"paper_id": "p", "request_figure_assistant": True}, result_path=tmp_path / "owner-result.json")
    task = db.task(report.enqueued[-1])
    bundle = tmp_path / "bundle.json"
    output = tmp_path / "artifacts" / "figure-edits.zip"
    output.parent.mkdir()
    with ZipFile(output, "w") as archive:
        archive.writestr("figures/design.pdf", b"diagram")

    atomic_write_json(bundle, {"artifacts": [{
        "artifact_id": "figure-edits", "uri": output.as_uri(), "sha256": sha256_file(output),
    }]})
    monkeypatch.setattr(db, "result_bundle_path", lambda _: str(bundle))
    packet = owner._read_json(Path(task["input_path"]))
    (manuscript / "main.tex").write_text("edited by someone else")
    with pytest.raises(ValueError, match="changed during figure repair"):
        paper_figures.apply(db, paths, task, packet, owner._read_json)
    assert not (manuscript / "figures/design.pdf").exists()
    (manuscript / "main.tex").write_text("original")

    owner._after_figure_repair(db, paths, settings, report, task=task, successful=True)
    review = db.task(report.enqueued[-1])
    assert (manuscript / "figures/design.pdf").read_bytes() == b"diagram"
    assert not (paths.data / "papers/p/manuscript/figures/design.pdf").exists()
    assert review["task_type"] == "paper_review" and review["parent_task_id"] == seat["task_id"]


def test_figure_tex_scope_preserves_endpoint_and_result_text():
    path = Path("main.tex")
    before = br"Primary endpoint: 5%."
    addition = br"""
Figure~\ref{fig:design} shows the paired sampling.
\begin{figure}
\includegraphics{figures/design.pdf}
\caption{Paired sampling.}\label{fig:design}
\end{figure}
"""
    paper_figures._validate_tex(before, before + addition, path)
    with pytest.raises(ValueError, match="outside its scope"):
        paper_figures._validate_tex(before, before.replace(b"5", b"7") + addition, path)


def test_harvest_requires_bound_review_and_clean_figure(tmp_path, monkeypatch):
    import json
    paths = SimpleNamespace(data=tmp_path, program_control=tmp_path / "control")
    root = tmp_path / "papers/p/manuscript"
    source = root / "figure-src/design.svg"
    pdf = root / "figures/design.pdf"
    for path in (source, pdf):
        path.parent.mkdir(parents=True)
        path.write_text("reviewed")
    record = dict(paper_id="p", merged={"outcome": "ready"}, letter="Referees accept the design.",
                  figure_metrics={"check_passed": True},
                  figure_sources=[dict(source=source.name, pdf=pdf.name, source_sha256=sha256_file(source),
                                       pdf_sha256=sha256_file(pdf))])
    decision = tmp_path / "decision.json"
    decision.write_text(json.dumps(record))
    binding = dict(field="energy", decision=decision.name, sha256=sha256_file(decision))
    audit = dict(manuscript=str(root), valid=True, blocking=[], repair_required=[])
    monkeypatch.setattr(paper_figures, "check", lambda *_: audit)
    def run():
        return paper_figures.harvest(paths, None, "p", binding)
    first = run()
    assert len(first) == 1 and run() == first
    dest = Path(first[0])
    assert dest.is_relative_to(paths.program_control / "figure-templates/_harvest/energy/p")
    assert json.loads((dest.parent / "provenance.json").read_text())["review_excerpt"] == record["letter"]
    audit["repair_required"] = ["unresolved"]
    assert run() == []
    audit["repair_required"] = []
    source.write_text("new")
    assert run() == [] and dest.read_text() == "reviewed"
    source.write_text("reviewed")
    pdf.write_text("changed")
    assert run() == []
    pdf.write_text("reviewed")
    record["merged"]["outcome"] = "revise"
    decision.write_text(json.dumps(record))
    assert run() == []
    binding["sha256"] = sha256_file(decision)
    assert run() == []


def test_metrics_follow_bound_decisions_and_count_distinct_seats(tmp_path, monkeypatch):
    import json
    paths, db, _, manuscript, _, _ = _fixture(tmp_path, monkeypatch)
    root = manuscript.parents[2]
    path = root / "decision.json"
    metric = dict(schematic_count=2, result_count=4, check_passed=True, required_changes=1,
                  figure_seats=0)
    campaign = {"state_path": str(root)}
    path.write_text(json.dumps(dict(paper_id="p", figure_metrics=metric)))
    paper_figures.record_review_metrics(db, paths, campaign, path.name, "bad")
    assert paper_figures.latest_metrics(db) == {}
    for _ in range(2):
        paper_figures.record_review_metrics(db, paths, campaign, path.name, sha256_file(path))
        db.record_event_once("paper", "p", "figure_seat", {}, event_key="seat-1")
    assert paper_figures.latest_metrics(db) == {"p": {**metric, "figure_seats": 1}}
    assert len(db.events(entity_type="figure_review")) == 1


def _with_figure_runners(settings, **owner_changes):
    runners = dict(settings.runners)
    runners["worker_claude"] = RunnerSpec(name="worker_claude", provider="anthropic", tier="worker",
                                          model="claude-opus-5-5")
    runners["light_claude"] = RunnerSpec(name="light_claude", provider="anthropic", tier="light",
                                         model="claude-haiku-5-5")
    return replace(settings, runners=runners, program=replace(
        settings.program, owner=replace(settings.program.owner, **owner_changes)))


def _queue_repair(tmp_path, monkeypatch, **owner_changes):
    paths, db, settings, manuscript, report, seat = _fixture(tmp_path, monkeypatch)
    settings = _with_figure_runners(settings, **owner_changes)
    monkeypatch.setattr(paper_figures, "check", lambda *_: {
        "manuscript": str(manuscript), "blocking": [],
        "repair_required": [{"figure": "plan", "code": "FIG-SCHEMATIC-MISSING", "message": "Draw design."}],
    })
    owner._enqueue_review(db, paths, settings, report, task=seat,
                          packet={"paper_id": "p", "request_figure_assistant": True},
                          result_path=tmp_path / "owner-result.json")
    repair = db.task(report.enqueued[-1])
    assert repair["task_type"] == paper_figures.TASK_TYPE
    return db, settings, report, seat, repair


def test_figure_seat_goes_to_the_writing_runner(tmp_path, monkeypatch):
    # User decision 2026-11-23: figures are drawn by the writer (Claude Opus).
    db, settings, _report, seat, repair = _queue_repair(tmp_path, monkeypatch,
                                                        writing_runner="worker_claude")
    assert seat["runner"] != "worker_claude"
    assert repair["runner"] == "worker_claude" and repair["runner_request"] is None
    assert repair["parent_task_id"] == seat["task_id"]


def test_figure_runner_overrides_the_writer_and_unset_keeps_the_asking_seat(tmp_path, monkeypatch):
    _db, _s, _r, _seat, repair = _queue_repair(tmp_path / "a", monkeypatch,
                                               writing_runner="worker_claude",
                                               figure_runner="light_claude")
    assert repair["runner"] == "light_claude"
    _db, _s, _r, seat, repair = _queue_repair(tmp_path / "b", monkeypatch)
    assert repair["runner"] == seat["runner"]
    # A figure runner that is not configured (e.g. its provider suspended) counts as unset.
    _db, _s, _r, seat, repair = _queue_repair(tmp_path / "c", monkeypatch,
                                              writing_runner="worker_claude",
                                              figure_runner="missing_runner")
    assert repair["runner"] == "worker_claude"


def test_figure_seat_waits_for_its_runner_then_falls_back_to_the_asking_runner(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    db, settings, report, seat, repair = _queue_repair(tmp_path, monkeypatch,
                                                       writing_runner="worker_claude",
                                                       writing_wait_hours=6)
    monkeypatch.setattr(owner, "runner_usable", lambda _s, _r, name: name != "worker_claude")
    now = datetime.now(UTC)
    for hours in (0, 3, 5.9):
        assert owner.supervise_figure_seats(db, settings, report, object(),
                                            now=now + timedelta(hours=hours)) == []
        assert db.task(repair["task_id"])["runner"] == "worker_claude"
    moves = owner.supervise_figure_seats(db, settings, report, object(), now=now + timedelta(hours=6.1))
    assert moves and moves[0]["to_runner"] == seat["runner"]
    assert moves[0]["reason"] == "figure_runner_unavailable"
    moved = db.task(repair["task_id"])
    assert moved["runner"] == seat["runner"] and moved["session_mode"] == "fresh"
    assert report.program["figure_repairs"][-1]["kind"] == "fallback"


def test_usable_figure_runner_clears_the_wait(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    db, settings, report, _seat, repair = _queue_repair(tmp_path, monkeypatch,
                                                        writing_runner="worker_claude",
                                                        writing_wait_hours=6)
    usable = {"value": False}
    monkeypatch.setattr(owner, "runner_usable", lambda *_a: usable["value"])
    now = datetime.now(UTC)
    owner.supervise_figure_seats(db, settings, report, object(), now=now)
    usable["value"] = True
    owner.supervise_figure_seats(db, settings, report, object(), now=now + timedelta(hours=5))
    usable["value"] = False
    # The wait restarts: 6.1 h after the first sighting is only 1.1 h of a new wait.
    assert owner.supervise_figure_seats(db, settings, report, object(),
                                        now=now + timedelta(hours=5)) == []
    assert owner.supervise_figure_seats(db, settings, report, object(),
                                        now=now + timedelta(hours=6.1)) == []
    assert db.task(repair["task_id"])["runner"] == "worker_claude"
