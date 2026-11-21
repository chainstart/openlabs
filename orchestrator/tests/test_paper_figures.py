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
    settings = replace(settings, runners={
        "worker_gpt": RunnerSpec(name="worker_gpt", provider="openai-codex", tier="worker", model="gpt"),
    })
    campaign_root = Path(db.campaign(topic["campaign_id"])["state_path"])
    manuscript = campaign_root / "papers" / "p" / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text("original")
    shared = paths.data / "papers" / "p" / "manuscript"
    shared.mkdir(parents=True)
    (shared / "main.tex").write_text("delivered")
    report = SimpleNamespace(enqueued=[], program={}, errors=[])
    return paths, db, settings, manuscript, report, _latest(db, topic["campaign_id"])


def test_missing_schematic_queues_worker_twice_then_owner(tmp_path, monkeypatch):
    paths, db, settings, manuscript, report, seat = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(paper_figures, "check", lambda *_: {
        "manuscript": str(manuscript), "blocking": [],
        "repair_required": [{"figure": "plan", "code": "FIG-SCHEMATIC-MISSING", "message": "Draw design."}],
    })
    result_path = tmp_path / "owner-result.json"
    args = {"task": seat, "packet": {"paper_id": "p"}, "result_path": result_path}
    assert owner._enqueue_review(db, paths, settings, report, **args) is None
    first = db.task(report.enqueued[-1])
    assert first["task_type"] == paper_figures.TASK_TYPE
    assert first["runner"] == "worker_gpt" and first["max_attempts"] == 1
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
                          packet={"paper_id": "p"}, result_path=tmp_path / "owner-result.json")
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
