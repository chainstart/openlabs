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

    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    target = lane["selected_target"]
    assert lane["stage"] == "research"
    assert target["selection_basis"] == "operator_locked_route"
    assert "scores" not in target
    campaign = lane_path.parent / target["amra_campaign"] / "campaign_state.json"
    assert campaign.is_file()
    assert json.loads(campaign.read_text(encoding="utf-8"))["phase"] == "target_selection"
