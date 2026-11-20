"""The Stop gate reports campaign data-boundary violations while the agent can still fix them.

2026-11-20: a power-line scout saved an AEMO specification PDF under the campaign's
evidence/ directory; the promotion refused it at ingest and the whole scout run was lost.
The same rule now blocks the first Stop with the place the file belongs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openlabs import codex_hook
from openlabs.attempts import (
    ATTEMPT_SCHEMA,
    AttemptWorkspace,
    AttemptWorkspaceError,
    _tree_manifest,
    artifact_policy_payload,
    enforce_campaign_data_boundary,
)
from openlabs.contracts import RESULT_SCHEMA, atomic_write_json

EXPECTED = {"schema_version": RESULT_SCHEMA, "task_id": "topic-scout:x", "campaign_id": "c1",
            "lab_id": "quant", "domain": "quant"}


def _attempt(tmp_path: Path) -> tuple[dict, AttemptWorkspace]:
    root = tmp_path / "attempt"
    campaign = root / "workspaces" / "quant" / "c1"
    staging = root / "artifact-stage"
    (campaign / "evidence").mkdir(parents=True)
    staging.mkdir()
    (campaign / "notes.md").write_text("baseline\n")
    atomic_write_json(root / "attempt-workspace.json", {
        "schema_version": ATTEMPT_SCHEMA, "task_id": "topic-scout:x", "campaign_id": "c1",
        "attempt_id": "a1", "domain": "quant", "status": "active",
        "canonical_campaign_root": str(tmp_path / "canonical"),
        "staged_campaign_root": str(campaign), "artifact_staging_root": str(staging),
        "artifact_policy": artifact_policy_payload(), "baseline": _tree_manifest(campaign)})
    result = campaign / "results" / "result.json"
    atomic_write_json(result, {**EXPECTED, "status": "completed", "summary": "s",
                               "artifacts": [], "claims": [], "next_actions": []})
    context = {"result_path": str(result), "agent_workspace": str(campaign),
               "canonical_campaign_workspace": str(tmp_path / "canonical"),
               "expected_result": dict(EXPECTED), "protocol_binding": None,
               "attempt_root": str(root), "artifact_staging_root": str(staging)}
    workspace = AttemptWorkspace(root=root, domain_root=root / "workspaces" / "quant",
                                 campaign_root=campaign,
                                 canonical_domain_root=tmp_path / "canonical-domain",
                                 canonical_campaign_root=tmp_path / "canonical",
                                 metadata_path=root / "attempt-workspace.json")
    return context, workspace


def test_a_pdf_in_the_campaign_evidence_blocks_the_first_stop_with_the_staging_root(tmp_path):
    context, workspace = _attempt(tmp_path)
    pdf = workspace.campaign_root / "evidence" / "scout-a15906ed" / "aemo-emms-v53.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.7\nspec\n")
    (workspace.campaign_root / "evidence" / "receipt.json").write_text("{}\n")

    problems = codex_hook._data_boundary_problems(context)
    assert len(problems) == 1
    assert "evidence/scout-a15906ed/aemo-emms-v53.pdf uses artifact-only format" in problems[0]
    assert str(workspace.artifact_staging_root) in problems[0]
    assert "receipt.json" not in problems[0]
    output, outcome, reason = codex_hook._stop_evaluation({}, context)
    assert output["decision"] == "block" and outcome == "result_gate_blocked"
    assert "aemo-emms-v53.pdf" in reason
    # The ingest rule agrees: this exact campaign would be refused at promotion.
    with pytest.raises(AttemptWorkspaceError, match="aemo-emms-v53.pdf"):
        enforce_campaign_data_boundary(workspace)

    # The agent moves the PDF to artifact staging: the boundary is clean, as at ingest.
    target = workspace.artifact_staging_root / "evidence" / "scout-a15906ed" / pdf.name
    target.parent.mkdir(parents=True)
    pdf.replace(target)
    assert codex_hook._data_boundary_problems(context) == []
    assert enforce_campaign_data_boundary(workspace) == ("evidence/receipt.json",)


def test_an_oversized_text_file_is_reported_too(tmp_path):
    context, workspace = _attempt(tmp_path)
    (workspace.campaign_root / "evidence" / "sample.csv").write_bytes(b"1,2\n" * 1_400_000)
    problems = codex_hook._data_boundary_problems(context)
    assert problems and "evidence/sample.csv is 5600000 bytes" in problems[0]


def test_no_attempt_root_or_a_pre_policy_attempt_is_not_checked(tmp_path):
    context, workspace = _attempt(tmp_path)
    (workspace.campaign_root / "run.log").write_text("x\n")
    assert codex_hook._data_boundary_problems({**context, "attempt_root": None}) == []
    metadata = json.loads(workspace.metadata_path.read_text())
    metadata.pop("artifact_policy")
    atomic_write_json(workspace.metadata_path, metadata)
    assert codex_hook._data_boundary_problems(context) == []


def test_session_start_names_the_artifact_staging_root(tmp_path):
    context, workspace = _attempt(tmp_path)
    message = codex_hook._session_context({**context, "skills": []})[
        "hookSpecificOutput"]["additionalContext"]
    assert str(workspace.artifact_staging_root) in message and "PDF" in message
