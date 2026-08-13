from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openlabs.contracts import atomic_write_json

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "labs"
    / "math"
    / "skills"
    / "math-production-supervisor"
    / "scripts"
    / "production_lane.py"
)


def _lane(tmp_path: Path, *, selection_mode: str = "radar_scored") -> Path:
    plan_path = tmp_path / "production_plan.json"
    lane_path = tmp_path / "production_lane.json"
    atomic_write_json(plan_path, {"plan_id": "test-plan"})
    lane = {
        "schema_version": "openlabs.math_production_lane.v1",
        "plan_id": "test-plan",
        "lane_id": "test-lane",
        "plan_path": "production_plan.json",
        "selection_mode": selection_mode,
        "stage": "radar",
        "cycle": 1,
        "theme": {"name": "Test"},
        "selection_gate": {},
        "node_policy": {
            "consecutive_no_progress_limit": 3,
            "max_radar_nodes_per_cycle": 2,
            "max_nodes_without_theorem_delta": 3,
            "max_research_nodes_per_target": 6,
            "max_frozen_branches_without_promotion": 2,
        },
        "selected_target": None,
        "archived_targets": [],
        "nodes": [],
        "history": [],
    }
    if selection_mode == "operator_locked_route":
        lane["route"] = {
            "name": "A fixed route",
            "frontier": "A precise published frontier",
        }
    atomic_write_json(lane_path, lane)
    return lane_path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _lock_operator_route(lane_path: Path) -> dict:
    result = _run(
        "lock-route",
        "--lane",
        str(lane_path),
        "--target-id",
        "fixed-frontier-target",
        "--problem-id",
        "rh-route",
        "--title",
        "Advance a fixed RH route",
        "--statement",
        "Prove the configured strict frontier improvement.",
        "--source",
        "https://arxiv.org/abs/2405.20552",
        "--frontier",
        "Published exponent 30/13.",
        "--first-kill-test",
        "Test the proposed estimate in the critical parameter regime.",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(lane_path.read_text(encoding="utf-8"))


def _set_current_amra_phase(lane_path: Path, phase: str) -> None:
    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    state_path = (
        lane_path.parent
        / lane["selected_target"]["amra_campaign"]
        / "campaign_state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = phase
    atomic_write_json(state_path, state)


def test_unselected_radar_cannot_claim_progress_and_exhausts(tmp_path) -> None:
    lane_path = _lane(tmp_path)
    rejected = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "progress",
        "--delta-kind",
        "blocker_reduced",
        "--summary",
        "Only bibliography changed.",
        "--evidence",
        "search.json",
    )
    assert rejected.returncode == 2
    assert "can only be recorded as no_progress" in rejected.stderr

    for index in (1, 2):
        recorded = _run(
            "record-node",
            "--lane",
            str(lane_path),
            "--outcome",
            "no_progress",
            "--summary",
            f"Empty radar pass {index}.",
        )
        assert recorded.returncode == 0, recorded.stderr

    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    assert lane["stage"] == "terminal"
    assert [node["outcome"] for node in lane["nodes"]] == [
        "no_progress",
        "no_progress",
    ]


def test_operator_route_lock_skips_candidate_scores_and_initializes_amra(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    lane = _lock_operator_route(lane_path)
    target = lane["selected_target"]
    assert lane["stage"] == "research"
    assert target["selection_basis"] == "operator_locked_route"
    assert "scores" not in target
    campaign = lane_path.parent / target["amra_campaign"] / "campaign_state.json"
    assert campaign.is_file()
    assert json.loads(campaign.read_text(encoding="utf-8"))["phase"] == "target_selection"


def test_search_progress_does_not_reset_theorem_stall(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    _lock_operator_route(lane_path)

    payload = None
    for index in (1, 2, 3):
        result = _run(
            "record-node",
            "--lane",
            str(lane_path),
            "--outcome",
            "progress",
            "--delta-kind",
            "mechanism_killed",
            "--summary",
            f"Mechanism {index} failed its kill test.",
            "--evidence",
            f"evidence/kill-{index}.json",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)

    assert payload is not None
    assert payload["progress_class"] == "search"
    assert payload["consecutive_no_progress"] == 0
    assert payload["consecutive_without_theorem_delta"] == 3
    assert payload["freeze_required"] is True
    assert "max_nodes_without_theorem_delta" in payload["freeze_reasons"]

    rejected = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "progress",
        "--delta-kind",
        "blocker_reduced",
        "--summary",
        "Try one more local branch.",
        "--evidence",
        "evidence/fourth.json",
    )
    assert rejected.returncode == 2
    assert "requires AMRA freeze" in rejected.stderr

    salvage = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "progress",
        "--delta-kind",
        "standalone_no_go_closed",
        "--summary",
        "Package the existing kill evidence as a standalone no-go theorem.",
        "--evidence",
        "evidence/no-go-proof.md",
        "--theorem-statement",
        "No mechanism in the frozen representation class can close the target.",
        "--theorem-scope",
        "The exactly declared representation class and unconditional inputs.",
        "--theorem-consequence",
        "Closes the public mechanism question within that class.",
    )
    assert salvage.returncode == 0, salvage.stderr
    assert json.loads(salvage.stdout)["audit_required"] is True

    _set_current_amra_phase(lane_path, "frozen")
    frozen = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "freeze",
        "--summary",
        "Freeze after theorem-scale stagnation.",
    )
    assert frozen.returncode == 0, frozen.stderr


def test_theorem_delta_requires_auditable_statement_and_forces_review(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    _lock_operator_route(lane_path)

    incomplete = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "progress",
        "--delta-kind",
        "public_frontier_improved",
        "--summary",
        "Claim an improved density proportion.",
        "--evidence",
        "evidence/proof.md",
    )
    assert incomplete.returncode == 2
    assert "requires --theorem-statement" in incomplete.stderr

    theorem = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "progress",
        "--delta-kind",
        "public_frontier_improved",
        "--summary",
        "Obtain a paper-scale unconditional improvement.",
        "--evidence",
        "evidence/proof.md",
        "--theorem-statement",
        "At least 0.68 of the relevant zeros satisfy the stated property.",
        "--theorem-scope",
        "All sufficiently large heights under the declared unconditional inputs.",
        "--theorem-consequence",
        "Strictly improves the published 0.6725 frontier.",
    )
    assert theorem.returncode == 0, theorem.stderr
    payload = json.loads(theorem.stdout)
    assert payload["progress_class"] == "theorem"
    assert payload["audit_required"] is True
    assert payload["consecutive_without_theorem_delta"] == 0

    continued = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "progress",
        "--delta-kind",
        "survivor_strengthened",
        "--summary",
        "Continue author-side derivation before review.",
        "--evidence",
        "evidence/more.md",
    )
    assert continued.returncode == 2
    assert "requires an independent audit" in continued.stderr

    _set_current_amra_phase(lane_path, "promotion")
    promoted = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "promotion",
        "--summary",
        "Fresh reviewer reconstructed the theorem.",
    )
    assert promoted.returncode == 0, promoted.stderr


def test_frozen_route_branch_requires_amendment_and_is_bounded(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    lane = _lock_operator_route(lane_path)
    campaign_state = (
        lane_path.parent
        / lane["selected_target"]["amra_campaign"]
        / "campaign_state.json"
    )
    state = json.loads(campaign_state.read_text(encoding="utf-8"))
    state["phase"] = "frozen"
    atomic_write_json(campaign_state, state)

    common = (
        "branch-route",
        "--lane",
        str(lane_path),
        "--target-id",
        "amended-target",
        "--problem-id",
        "rh-route-amended",
        "--title",
        "Amended RH frontier target",
        "--statement",
        "Prove a weaker but standalone unconditional density improvement.",
        "--source",
        "https://example.test/source",
        "--first-kill-test",
        "Test the repaired mass matrix on adversarial spectra.",
        "--reason",
        "The first audit exposed a mass-matrix gap.",
    )
    missing = _run(*common)
    assert missing.returncode == 2
    assert "requires --amendment" in missing.stderr

    branched = _run(
        *common,
        "--amendment",
        "Replace the invalid identity by a generalized eigenvalue statement.",
        "--defect-addressed",
        "The new statement explicitly includes and controls the mass matrix.",
    )
    assert branched.returncode == 0, branched.stderr

    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    second_state = (
        lane_path.parent
        / lane["selected_target"]["amra_campaign"]
        / "campaign_state.json"
    )
    state = json.loads(second_state.read_text(encoding="utf-8"))
    state["phase"] = "frozen"
    atomic_write_json(second_state, state)
    bounded = _run(
        "branch-route",
        "--lane",
        str(lane_path),
        "--target-id",
        "third-target",
        "--problem-id",
        "rh-route-third",
        "--title",
        "Third RH target",
        "--statement",
        "Prove another modified density result.",
        "--source",
        "https://example.test/source-2",
        "--first-kill-test",
        "Run the decisive spectral test.",
        "--reason",
        "Attempt another repair.",
        "--amendment",
        "Change the operator domain.",
        "--defect-addressed",
        "Restrict to the domain where the form is closable.",
    )
    assert bounded.returncode == 2
    assert "route branch limit reached" in bounded.stderr
