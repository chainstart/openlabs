from __future__ import annotations

import json
import importlib.util
from hashlib import sha256
import subprocess
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
import jsonschema

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
RESEARCH_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "labs"
    / "math"
    / "skills"
    / "amra-research-loop"
    / "scripts"
    / "research_loop.py"
)
SELECTION_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "labs" / "math" / "skills" / "math-production-supervisor"
    / "schemas" / "math-target-selection.schema.json"
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


def test_amra_loader_uses_a_private_absolute_module(monkeypatch) -> None:
    poisoned = types.ModuleType("loop_core")
    poisoned.__file__ = "/tmp/poisoned-loop-core.py"
    monkeypatch.setitem(sys.modules, "loop_core", poisoned)
    original_path = list(sys.path)

    spec = importlib.util.spec_from_file_location(
        "_test_math_production_lane_module",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = module._load_amra_loop_core()

    assert Path(loaded.__file__).resolve() == module._AMRA_LOOP_CORE_PATH
    assert loaded.__name__ == "_openlabs_math_production_amra_loop_core"
    assert sys.modules["loop_core"] is poisoned
    assert sys.path == original_path


def _write_selection_receipt(
    lane_path: Path,
    *,
    target_id: str,
    problem_id: str,
    title: str,
    statement: str,
    source: str,
    candidate_count: int = 4,
    research_front_count: int = 4,
    selection_gate_snapshot: dict | None = None,
) -> Path:
    radar = lane_path.parent / "radar" / "cycle-001"
    source_artifact = radar / "primary-source.html"
    source_artifact.parent.mkdir(parents=True, exist_ok=True)
    source_artifact.write_text(
        f"<h1>Primary source</h1><p>{statement}</p><p>Status: open conjecture.</p>",
        encoding="utf-8",
    )
    status_artifact = radar / "open-status.md"
    status_artifact.write_text(
        f"Checked the primary source at {source}; it labels the statement open.\n",
        encoding="utf-8",
    )
    novelty_artifact = radar / "duplicate-search.md"
    novelty_artifact.write_text(
        "Compared the exact statement against the closest published result; no closure found.\n",
        encoding="utf-8",
    )
    scores = {
        "novelty": 0,
        "significance": 0,
        "closure": 0,
        "auditability": 0,
        "generality": 0,
        "venue_fit": 0,
        "total": 0,
    }
    if selection_gate_snapshot is None:
        selection_gate_snapshot = dict(
            json.loads(lane_path.read_text(encoding="utf-8"))["selection_gate"]
        )
        selection_gate_snapshot.setdefault("minimum_target_cards", 4)
        selection_gate_snapshot.setdefault("minimum_distinct_research_fronts", 1)
    cards = radar / "target_cards.json"
    atomic_write_json(
        cards,
        {
            "candidates": [
                {
                    "target_id": target_id,
                    "problem_id": problem_id,
                    "title": title,
                    "source_original_statement": statement,
                    "frozen_target_statement": statement,
                    "target_relation": "exact",
                    "source": source,
                    "research_front": "front-0",
                    "public_status": "open_conjecture",
                    "source_locator": "Problem 1.1",
                    "closest_published_result": "The cited paper proves only the finite comparison range.",
                    "score_vector": scores,
                    "blocking_novelty_risk": False,
                },
                *[
                    {
                        "target_id": f"comparison-{index}",
                        "problem_id": f"comparison-{index}",
                        "title": f"Comparison target {index}",
                        "source_original_statement": f"Comparison statement {index}",
                        "frozen_target_statement": f"Comparison statement {index}",
                        "target_relation": "exact",
                        "source": f"https://example.test/comparison-{index}",
                        "research_front": f"front-{index % research_front_count}",
                        "public_status": "open_problem",
                        "source_locator": f"Problem {index + 1}.1",
                        "score_vector": scores,
                        "blocking_novelty_risk": False,
                        "closest_published_result": f"Comparison result {index}.",
                    }
                    for index in range(1, candidate_count)
                ],
            ]
        },
    )
    cards_digest = sha256(cards.read_bytes()).hexdigest()
    receipt = radar / "selection.json"
    atomic_write_json(
        receipt,
        {
            "schema": "openlabs.math_target_selection.v1",
            "target_id": target_id,
            "problem_id": problem_id,
            "title": title,
            "source_original_statement": statement,
            "frozen_target_statement": statement,
            "target_relation": "exact",
            "source": source,
            "research_front": "front-0",
            "source_kind": "primary",
            "source_statement_quote": statement,
            "open_status_quote": "Status: open conjecture.",
            "source_locator": "Problem 1.1",
            "public_status": "open_conjecture",
            "status_checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "score_vector": scores,
            "selection_gate_snapshot": selection_gate_snapshot,
            "selection_plan_sha256": sha256(
                (lane_path.parent / "production_plan.json").read_bytes()
            ).hexdigest(),
            "blocking_novelty_risk": False,
            "closest_published_result": "The cited paper proves only the finite comparison range.",
            "duplicate_search_checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "novelty_evidence": [{
                "path": novelty_artifact.name,
                "sha256": sha256(novelty_artifact.read_bytes()).hexdigest(),
            }],
            "source_artifact": {
                "path": source_artifact.name,
                "sha256": sha256(source_artifact.read_bytes()).hexdigest(),
            },
            "status_evidence": [
                {
                    "path": status_artifact.name,
                    "sha256": sha256(status_artifact.read_bytes()).hexdigest(),
                }
            ],
            "target_cards": "target_cards.json",
            "target_cards_sha256": cards_digest,
        },
    )
    return receipt


def _select_exact_target(
    lane_path: Path,
    receipt: Path,
    *,
    target_id: str,
    problem_id: str,
    title: str,
    statement: str,
    source: str,
) -> subprocess.CompletedProcess[str]:
    return _run(
        "select",
        "--lane",
        str(lane_path),
        "--target-id",
        target_id,
        "--problem-id",
        problem_id,
        "--title",
        title,
        "--source-statement",
        statement,
        "--target-statement",
        statement,
        "--target-relation",
        "exact",
        "--source",
        source,
        "--selection-receipt",
        str(receipt),
        "--first-kill-test",
        "Test the first hostile model.",
        "--novelty",
        "0",
        "--significance",
        "0",
        "--closure",
        "0",
        "--auditability",
        "0",
        "--generality",
        "0",
        "--venue-fit",
        "0",
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
        "--source-statement",
        "Prove the Riemann hypothesis.",
        "--target-statement",
        "Prove the configured strict frontier improvement.",
        "--target-relation",
        "partial",
        "--source",
        "https://arxiv.org/abs/2405.20552",
        "--frontier",
        "Published exponent 30/13.",
        "--first-kill-test",
        "Test the proposed estimate in the critical parameter regime.",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(lane_path.read_text(encoding="utf-8"))


def _record_theorem_delta(lane_path: Path) -> subprocess.CompletedProcess[str]:
    return _run(
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


def _current_amra_path(lane_path: Path) -> Path:
    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    return (
        lane_path.parent
        / lane["selected_target"]["amra_campaign"]
    )


def _freeze_current_amra(lane_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RESEARCH_SCRIPT),
            "freeze",
            "--campaign",
            str(_current_amra_path(lane_path)),
            "--reason",
            "The configured research route is exhausted.",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _forge_incomplete_promotion_with_valid_history(lane_path: Path) -> None:
    campaign_path = _current_amra_path(lane_path)
    state_path = campaign_path / "campaign_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    phases = [
        "target_selection",
        "obstruction_analysis",
        "representation_search",
        "mechanism_falsification",
        "survivor_deepening",
        "independent_audit",
        "promotion",
    ]
    at = state["updated_at"]
    state["history"] = [state["history"][0]] + [
        {
            "at": at,
            "event": "advanced",
            "from": previous,
            "phase": current,
        }
        for previous, current in zip(phases, phases[1:])
    ]
    state["phase"] = "promotion"
    atomic_write_json(state_path, state)
    decision_path = campaign_path / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision.update(
        {
            "outcome": "promote",
            "success_condition": "scoped_theorem_proved",
            "reason": "Forged terminal metadata without proof or audit artifacts.",
            "evidence": ["missing-proof.md"],
        }
    )
    atomic_write_json(decision_path, decision)


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


def test_radar_selection_rejects_a_scoped_target(tmp_path) -> None:
    lane_path = _lane(tmp_path)
    rejected = _run(
        "select",
        "--lane",
        str(lane_path),
        "--target-id",
        "narrow-specialization",
        "--problem-id",
        "open-problem",
        "--title",
        "A narrowed target",
        "--source-statement",
        "Prove P for every finite graph.",
        "--target-statement",
        "Prove P for every finite planar graph.",
        "--target-relation",
        "specialization",
        "--source",
        "https://example.test/open-problem",
        "--first-kill-test",
        "Test the smallest excluded graph.",
        "--novelty",
        "25",
        "--significance",
        "25",
        "--closure",
        "20",
        "--auditability",
        "15",
        "--generality",
        "10",
        "--venue-fit",
        "5",
    )
    assert rejected.returncode == 2
    assert "open-problem selection requires target_relation=exact" in rejected.stderr
    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    assert lane["stage"] == "radar"
    assert lane["selected_target"] is None


def test_radar_selection_requires_and_binds_primary_source_receipt(tmp_path) -> None:
    lane_path = _lane(tmp_path)
    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    lane["selection_gate"] = {
        "minimum_total": 0,
        "minimum_novelty": 0,
        "minimum_significance": 0,
        "minimum_closure": 0,
    }
    atomic_write_json(lane_path, lane)
    statement = "For every finite graph G, prove P(G)."
    source = "https://example.test/primary-open-conjecture"
    receipt = _write_selection_receipt(
        lane_path,
        target_id="full-open-conjecture",
        problem_id="open-conjecture-1",
        title="Full open conjecture",
        statement=statement,
        source=source,
    )
    jsonschema.validate(
        json.loads(receipt.read_text(encoding="utf-8")),
        json.loads(SELECTION_SCHEMA.read_text(encoding="utf-8")),
    )
    selected = _run(
        "select",
        "--lane",
        str(lane_path),
        "--target-id",
        "full-open-conjecture",
        "--problem-id",
        "open-conjecture-1",
        "--title",
        "Full open conjecture",
        "--source-statement",
        statement,
        "--target-statement",
        statement,
        "--target-relation",
        "exact",
        "--source",
        source,
        "--selection-receipt",
        str(receipt),
        "--first-kill-test",
        "Test the first hostile model.",
        "--novelty",
        "0",
        "--significance",
        "0",
        "--closure",
        "0",
        "--auditability",
        "0",
        "--generality",
        "0",
        "--venue-fit",
        "0",
    )
    assert selected.returncode == 0, selected.stderr
    valid = _run("validate", "--lane", str(lane_path))
    assert valid.returncode == 0, valid.stdout

    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    receipt_payload["source_locator"] = "Silently replaced locator"
    atomic_write_json(receipt, receipt_payload)
    tampered = _run("validate", "--lane", str(lane_path))
    assert tampered.returncode == 1
    assert "selection_receipt SHA-256" in tampered.stdout


def test_plan_card_and_front_minima_are_mapped_enforced_and_hash_bound(tmp_path) -> None:
    lane_path = _lane(tmp_path)
    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    lane["selection_gate"] = {
        "minimum_total": 0,
        "minimum_novelty": 0,
        "minimum_significance": 0,
        "minimum_closure": 0,
    }
    atomic_write_json(lane_path, lane)
    plan_path = lane_path.parent / "production_plan.json"
    plan = {
        "plan_id": "test-plan",
        "selection_gate": {
            "minimum_total": 0,
            "minimum_novelty": 0,
            "minimum_significance": 0,
            "minimum_closure": 0,
            "minimum_target_cards_per_cycle": 6,
            "minimum_distinct_research_fronts_per_cycle": 3,
        },
        "program": {
            "research_fronts": [
                {"name": "front-0"},
                {"name": "front-1"},
                {"name": "front-2"},
            ]
        },
    }
    atomic_write_json(plan_path, plan)
    effective_gate = {
        **lane["selection_gate"],
        "minimum_target_cards": 6,
        "minimum_distinct_research_fronts": 3,
    }
    selection = {
        "target_id": "mapped-plan-target",
        "problem_id": "mapped-open-conjecture",
        "title": "Mapped production-plan target",
        "statement": "For every finite object X, prove Q(X).",
        "source": "https://example.test/mapped-open-conjecture",
    }

    receipt = _write_selection_receipt(
        lane_path,
        **selection,
        candidate_count=4,
        research_front_count=3,
        selection_gate_snapshot=effective_gate,
    )
    underfilled = _select_exact_target(lane_path, receipt, **selection)
    assert underfilled.returncode == 2
    assert "target_cards must compare at least 6 candidates" in underfilled.stderr

    receipt = _write_selection_receipt(
        lane_path,
        **selection,
        candidate_count=6,
        research_front_count=2,
        selection_gate_snapshot=effective_gate,
    )
    narrow = _select_exact_target(lane_path, receipt, **selection)
    assert narrow.returncode == 2
    assert "at least 3 distinct research fronts" in narrow.stderr

    receipt = _write_selection_receipt(
        lane_path,
        **selection,
        candidate_count=6,
        research_front_count=3,
        selection_gate_snapshot=effective_gate,
    )
    accepted = _select_exact_target(lane_path, receipt, **selection)
    assert accepted.returncode == 0, accepted.stderr
    selected = json.loads(lane_path.read_text(encoding="utf-8"))["selected_target"]
    assert selected["selection_gate_snapshot"] == effective_gate
    assert selected["selection_plan_sha256"] == sha256(plan_path.read_bytes()).hexdigest()

    plan["revision_note"] = "A post-selection plan mutation must not be silent."
    atomic_write_json(plan_path, plan)
    mutated = _run("validate", "--lane", str(lane_path))
    assert mutated.returncode == 1
    assert "production plan SHA-256 does not match" in mutated.stdout


def test_candidate_cards_cannot_use_scoped_closed_risky_or_forged_scores(tmp_path) -> None:
    lane_path = _lane(tmp_path)
    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    lane["selection_gate"] = {
        "minimum_total": 0,
        "minimum_novelty": 0,
        "minimum_significance": 0,
        "minimum_closure": 0,
    }
    atomic_write_json(lane_path, lane)
    selection = {
        "target_id": "strict-card-target",
        "problem_id": "strict-card-open-problem",
        "title": "Strict candidate-card target",
        "statement": "For every finite system S, prove R(S).",
        "source": "https://example.test/strict-card-open-problem",
    }
    cases = (
        (
            lambda card: card.__setitem__("target_relation", "specialization"),
            "must use target_relation=exact",
        ),
        (
            lambda card: card.__setitem__("public_status", "published_theorem"),
            "must be an open problem or open conjecture",
        ),
        (
            lambda card: card.__setitem__(
                "frozen_target_statement", "Prove R(S) only for planar systems."
            ),
            "narrows or changes the source-original statement",
        ),
        (
            lambda card: card.__setitem__("blocking_novelty_risk", True),
            "must clear blocking novelty risk",
        ),
        (
            lambda card: card["score_vector"].pop("venue_fit"),
            "complete bounded integer score_vector",
        ),
        (
            lambda card: card["score_vector"].__setitem__("novelty", 26),
            "complete bounded integer score_vector",
        ),
        (
            lambda card: card["score_vector"].__setitem__("total", 1),
            "score total is inconsistent",
        ),
    )

    for mutate, expected_error in cases:
        receipt = _write_selection_receipt(lane_path, **selection)
        cards_path = receipt.parent / "target_cards.json"
        cards = json.loads(cards_path.read_text(encoding="utf-8"))
        mutate(cards["candidates"][1])
        atomic_write_json(cards_path, cards)
        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
        receipt_payload["target_cards_sha256"] = sha256(cards_path.read_bytes()).hexdigest()
        atomic_write_json(receipt, receipt_payload)

        rejected = _select_exact_target(lane_path, receipt, **selection)
        assert rejected.returncode == 2
        assert expected_error in rejected.stderr


def test_radar_lane_validation_rejects_a_restored_scoped_target(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    lane = _lock_operator_route(lane_path)
    lane["selection_mode"] = "radar_scored"
    lane.pop("route", None)
    atomic_write_json(lane_path, lane)

    rejected = _run("validate", "--lane", str(lane_path))
    assert rejected.returncode == 1
    assert (
        "radar-scored selected_target must retain the exact source-original statement"
        in rejected.stdout
    )


def test_operator_route_lock_skips_candidate_scores_and_initializes_amra(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    lane = _lock_operator_route(lane_path)
    target = lane["selected_target"]
    assert lane["stage"] == "research"
    assert target["selection_basis"] == "operator_locked_route"
    assert target["source_original_statement"] == "Prove the Riemann hypothesis."
    assert target["target_relation"] == "partial"
    assert "scores" not in target
    campaign = lane_path.parent / target["amra_campaign"] / "campaign_state.json"
    assert campaign.is_file()
    assert json.loads(campaign.read_text(encoding="utf-8"))["phase"] == "target_selection"
    contract = json.loads(
        (campaign.parent / "closure_contract.json").read_text(encoding="utf-8")
    )
    assert contract["source_original_statement"] == "Prove the Riemann hypothesis."
    assert contract["frozen_target_statement"] == target["frozen_target_statement"]
    assert contract["success_conditions"] == ["scoped_theorem_proved"]


def test_research_lane_binds_selected_target_to_amra_contract(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    lane = _lock_operator_route(lane_path)
    original_source = lane["selected_target"].pop("source_original_statement")
    atomic_write_json(lane_path, lane)

    missing = _run("validate", "--lane", str(lane_path))
    assert missing.returncode == 1
    assert "selected_target needs source_original_statement" in missing.stdout

    lane["selected_target"]["source_original_statement"] = original_source
    lane["selected_target"]["frozen_target_statement"] = (
        "Prove a silently narrowed replacement theorem."
    )
    atomic_write_json(lane_path, lane)
    mismatched = _run("validate", "--lane", str(lane_path))
    assert mismatched.returncode == 1
    assert (
        "selected_target frozen_target_statement does not match AMRA closure contract"
        in mismatched.stdout
    )


def test_research_lane_runs_nested_amra_integrity(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    _lock_operator_route(lane_path)
    state_path = _current_amra_path(lane_path) / "campaign_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["statement_identity"]["frozen_target_sha256"] = "0" * 64
    atomic_write_json(state_path, state)

    rejected = _run("validate", "--lane", str(lane_path))
    assert rejected.returncode == 1
    assert "selected AMRA integrity" in rejected.stdout
    assert "frozen_target_statement changed" in rejected.stdout


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

    _freeze_current_amra(lane_path)
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

    _forge_incomplete_promotion_with_valid_history(lane_path)
    promoted = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "promotion",
        "--summary",
        "Fresh reviewer reconstructed the theorem.",
    )
    assert promoted.returncode == 2
    assert "selected AMRA integrity" in promoted.stderr
    assert "published comparator" in promoted.stderr


def test_continuation_gate_is_reduced_from_nodes_and_cannot_be_removed_or_tampered(
    tmp_path,
) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    _lock_operator_route(lane_path)
    theorem = _record_theorem_delta(lane_path)
    assert theorem.returncode == 0, theorem.stderr
    lane = json.loads(lane_path.read_text(encoding="utf-8"))
    authoritative_gate = dict(lane["continuation_gate"])
    assert authoritative_gate["status"] == "independent_audit_required"

    lane.pop("continuation_gate")
    atomic_write_json(lane_path, lane)
    removed = _run("validate", "--lane", str(lane_path))
    assert removed.returncode == 1
    assert "node-derived state (expected independent_audit_required)" in removed.stdout
    bypass = _run(
        "record-node",
        "--lane",
        str(lane_path),
        "--outcome",
        "progress",
        "--delta-kind",
        "blocker_reduced",
        "--summary",
        "Attempt to continue after deleting the gate.",
        "--evidence",
        "evidence/bypass.md",
    )
    assert bypass.returncode == 2
    assert "node-derived state" in bypass.stderr

    lane["continuation_gate"] = authoritative_gate
    lane["continuation_gate"]["theorem_delta"] = "mechanism_killed"
    atomic_write_json(lane_path, lane)
    tampered = _run("validate", "--lane", str(lane_path))
    assert tampered.returncode == 1
    assert "continuation_gate does not match the node-derived state" in tampered.stdout

    lane["continuation_gate"] = authoritative_gate
    lane["nodes"].append(
        {
            "at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "cycle": lane["cycle"],
            "outcome": "progress",
            "delta_kind": "blocker_reduced",
            "progress_class": "search",
            "summary": "A structurally valid node forged past the audit gate.",
            "evidence": ["evidence/forged.md"],
        }
    )
    atomic_write_json(lane_path, lane)
    forged = _run("validate", "--lane", str(lane_path))
    assert forged.returncode == 1
    assert "bypasses prior continuation gate independent_audit_required" in forged.stdout


def test_node_delta_progress_theorem_and_evidence_shapes_are_authoritative(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    _lock_operator_route(lane_path)
    theorem = _record_theorem_delta(lane_path)
    assert theorem.returncode == 0, theorem.stderr
    baseline = json.loads(lane_path.read_text(encoding="utf-8"))

    malformed_delta = json.loads(json.dumps(baseline))
    malformed_delta["nodes"][0]["delta_kind"] = {"invented": "delta"}
    atomic_write_json(lane_path, malformed_delta)
    checked = _run("validate", "--lane", str(lane_path))
    assert checked.returncode == 1
    assert "progress lacks an epistemic delta_kind" in checked.stdout

    malformed_class = json.loads(json.dumps(baseline))
    malformed_class["nodes"][0]["progress_class"] = "search"
    atomic_write_json(lane_path, malformed_class)
    checked = _run("validate", "--lane", str(lane_path))
    assert checked.returncode == 1
    assert "inconsistent progress_class" in checked.stdout

    malformed_theorem = json.loads(json.dumps(baseline))
    malformed_theorem["nodes"][0]["theorem"].pop("consequence")
    atomic_write_json(lane_path, malformed_theorem)
    checked = _run("validate", "--lane", str(lane_path))
    assert checked.returncode == 1
    assert "incomplete theorem metadata" in checked.stdout

    malformed_evidence = json.loads(json.dumps(baseline))
    malformed_evidence["nodes"][0]["evidence"] = [{"path": "evidence/proof.md"}]
    atomic_write_json(lane_path, malformed_evidence)
    checked = _run("validate", "--lane", str(lane_path))
    assert checked.returncode == 1
    assert "evidence must be a list of nonempty paths" in checked.stdout


def test_frozen_route_branch_requires_amendment_and_is_bounded(tmp_path) -> None:
    lane_path = _lane(tmp_path, selection_mode="operator_locked_route")
    lane = _lock_operator_route(lane_path)
    _freeze_current_amra(lane_path)

    common = (
        "branch-route",
        "--lane",
        str(lane_path),
        "--target-id",
        "amended-target",
        "--problem-id",
        "rh-route",
        "--title",
        "Amended RH frontier target",
        "--source-statement",
        "Prove the Riemann hypothesis.",
        "--target-statement",
        "Prove a weaker but standalone unconditional density improvement.",
        "--target-relation",
        "partial",
        "--source",
        "https://arxiv.org/abs/2405.20552",
        "--first-kill-test",
        "Test the repaired mass matrix on adversarial spectra.",
        "--reason",
        "The first audit exposed a mass-matrix gap.",
    )
    switched_problem = list(common)
    switched_problem[switched_problem.index("rh-route")] = "different-open-problem"
    switched = _run(*switched_problem)
    assert switched.returncode == 2
    assert "retain the original problem_id" in switched.stderr

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
    _freeze_current_amra(lane_path)
    bounded = _run(
        "branch-route",
        "--lane",
        str(lane_path),
        "--target-id",
        "third-target",
        "--problem-id",
        "rh-route",
        "--title",
        "Third RH target",
        "--source-statement",
        "Prove the Riemann hypothesis.",
        "--target-statement",
        "Prove another modified density result.",
        "--target-relation",
        "partial",
        "--source",
        "https://arxiv.org/abs/2405.20552",
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
