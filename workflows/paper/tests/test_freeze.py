"""A frozen paper keeps its records but no pipeline step advances it."""

from pathlib import Path

import pytest

from paper_writing.__main__ import main
from paper_writing.editorial_rewrite import run_rewrite
from paper_writing.handoff import (
    HandoffError,
    build_handoff_package,
    plan_ready_handoffs,
    validate_release_preconditions,
)
from paper_writing.operations import start_revision
from paper_writing.registry import (
    PaperFrozenError,
    freeze_block_reason,
    load_registry,
    write_paper_metadata,
)
from paper_writing.review_flow import run_review, runs_dir

PAPER_ID = "20261109-physics-hydrology-frozen-example"
SHA = "a" * 64


def _freeze_decision(**overrides):
    decision = {
        "status": "frozen",
        "decision": "freeze",
        "freeze_reason_class": "contribution_insufficient",
        "reason": "The decisive full-sample analysis reduced the main result to a known consequence.",
        "decided_at": "2026-11-12",
        "decided_by": {"role": "research_lead"},
        "freeze_evidence": [{"path": "maintenance/x/ASSESSMENT.md", "sha256": SHA}],
        "reopen_conditions": [{"type": "new_method", "description": "A preregistered new question."}],
    }
    decision.update(overrides)
    return decision


def _repo(tmp_path: Path, **paper) -> Path:
    registry = tmp_path / "registry"
    (registry / "papers").mkdir(parents=True)
    (registry / "settings.yaml").write_text(
        "schema_version: ara.paper_writing.registry.v1\n", encoding="utf-8"
    )
    (tmp_path / "papers" / PAPER_ID / "manuscript").mkdir(parents=True)
    record = {
        "paper_id": PAPER_ID,
        "created_at": "2026-11-09",
        "domain": "physics",
        "subdomain": "hydrology",
        "version": "0.8.1",
        "record_status": "frozen",
        "writing_release": {"status": "blocked", "pre_freeze_status": "revision_required"},
        "freeze_decision": _freeze_decision(),
    }
    record.update(paper)
    write_paper_metadata(PAPER_ID, record, tmp_path)
    return tmp_path


def test_valid_freeze_record_loads_and_reports_reason(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    paper = load_registry(root, include_local_repositories=False)["papers"][f"papers/{PAPER_ID}"]
    reason = freeze_block_reason(paper, PAPER_ID)
    assert reason and "frozen" in reason and "contribution_insufficient" in reason
    assert freeze_block_reason({"record_status": "paper_workspace"}) is None
    # Frozen discovery alone stops research, not writing.
    assert freeze_block_reason({"discovery_scheduling": "frozen"}) is None


def test_minimal_earlier_freeze_record_stays_valid(tmp_path: Path) -> None:
    root = _repo(tmp_path, freeze_decision={"status": "frozen", "reason": "Editorial rejection."})
    load_registry(root, include_local_repositories=False)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"freeze_decision": None}, "needs a freeze_decision"),
        ({"freeze_decision": _freeze_decision(freeze_reason_class="tired")}, "freeze_reason_class"),
        ({"freeze_decision": _freeze_decision(reason="")}, "reason is required"),
        ({"freeze_decision": _freeze_decision(freeze_evidence=[{"path": "x", "sha256": "1"}])}, "64-hex"),
        ({"freeze_decision": _freeze_decision(reopen_conditions=[{"type": "hope", "description": "x"}])},
         "reopen_conditions"),
        ({"freeze_decision": _freeze_decision(decided_at="12 Nov")}, "decided_at"),
        ({"writing_release": {"status": "ready"}}, "cannot keep writing_release.status ready"),
    ],
)
def test_invalid_freeze_records_are_rejected(tmp_path: Path, changes, message) -> None:
    root = _repo(tmp_path)
    from paper_writing.registry import load_paper_metadata

    record = load_paper_metadata(PAPER_ID, root)
    for key, value in changes.items():
        if value is None:
            record.pop(key)
        else:
            record[key] = value
    write_paper_metadata(PAPER_ID, record, root)
    with pytest.raises(ValueError, match=message):
        load_registry(root, include_local_repositories=False)


def test_review_rewrite_and_revision_refuse_a_frozen_paper(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(PaperFrozenError, match="is frozen"):
        run_review(PAPER_ID, root=root)
    assert not runs_dir(root, PAPER_ID).exists()
    with pytest.raises(PaperFrozenError, match="is frozen"):
        run_rewrite(PAPER_ID, root=root)
    with pytest.raises(PaperFrozenError, match="is frozen"):
        start_revision(PAPER_ID, "continue", root=root)
    assert not (root / "papers" / PAPER_ID / "revisions").exists()


def test_handoff_refuses_and_sync_skips_a_frozen_paper(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(HandoffError, match="is frozen"):
        validate_release_preconditions(PAPER_ID, root=root)
    with pytest.raises(HandoffError, match="is frozen"):
        build_handoff_package(PAPER_ID, root=root, output=tmp_path / "out")
    plan = plan_ready_handoffs([PAPER_ID], root=root)
    assert {"paper_id": PAPER_ID, "reason": "frozen", "status": "blocked"} in plan["skipped"]


def test_cli_reports_frozen_paper(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _repo(tmp_path)
    monkeypatch.setenv("OPENLABS_ENABLE_EXTERNAL_WRITES", "1")
    assert main(["zenodo", "prepare", "--paper-id", PAPER_ID, "--root", str(root),
                 "--config", str(root / "registry" / "settings.yaml")]) == 2
    assert "is frozen" in capsys.readouterr().out
    assert main(["review", "unified-run", "--paper-id", PAPER_ID, "--root", str(root)]) == 2
    assert '"frozen": true' in capsys.readouterr().out
    assert main(["rewrite", "run", PAPER_ID, "--root", str(root)]) == 2
    assert "is frozen" in capsys.readouterr().out
