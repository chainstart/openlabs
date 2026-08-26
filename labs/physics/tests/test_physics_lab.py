from __future__ import annotations

import json
import shutil
from pathlib import Path

from protocols.physics_research_protocol import validate
from tools.dataset_intake import _identifier
from tools.physics_runtime import report
from tools.problem_verdict import derive_problem_verdict, validate_resolution

LAB_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = LAB_ROOT / "protocols" / "examples"


def test_example_protocol_passes_discovery_and_commit() -> None:
    project = EXAMPLES / "project.json"
    state = EXAMPLES / "research_state.json"
    assert validate(project, state, mode="discovery") == []
    assert validate(project, state, mode="commit") == []


def test_verified_claim_requires_two_independent_routes(tmp_path: Path) -> None:
    fixture = tmp_path / "examples"
    shutil.copytree(EXAMPLES, fixture)
    state_path = fixture / "research_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["claims"][0]["status"] = "verified"
    state["paper_candidates"] = ["PCL-001"]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    errors = validate(fixture / "project.json", state_path, mode="discovery")
    assert any("requires 2 independent evidence" in error for error in errors)


def test_dataset_identifiers_reject_path_traversal() -> None:
    assert _identifier("gwosc-GW150914-v3", "dataset_id") == "gwosc-GW150914-v3"
    for value in ("../escape", "a/b", ""):
        try:
            _identifier(value, "dataset_id")
        except ValueError:
            pass
        else:  # pragma: no cover - defensive assertion.
            raise AssertionError(f"unsafe identifier accepted: {value}")


def test_runtime_inspection_has_no_physical_side_effects() -> None:
    payload = report(LAB_ROOT)
    assert payload["valid"] is True
    assert payload["safety"] == {
        "physical_experiment_execution_enabled": False,
        "instrument_control_enabled": False,
        "public_data_download_performed": False,
    }


def test_problem_verdict_cannot_claim_solution_before_a_route_is_complete() -> None:
    decision = json.loads(
        (EXAMPLES / "resolution_decision.json").read_text(encoding="utf-8")
    )
    decision["problem_verdict"] = "solved_positive"
    errors = validate_resolution(decision)
    assert any("machine-derived verdict 'open'" in error for error in errors)


def test_problem_verdict_is_derived_only_from_all_route_criteria() -> None:
    decision = json.loads(
        (EXAMPLES / "resolution_decision.json").read_text(encoding="utf-8")
    )
    route = decision["resolution_routes"][0]
    route["criteria"][0]["status"] = "met"
    route["criteria"][0]["evidence"] = ["independent-check.json"]
    decision["problem_verdict"] = "solved_positive"
    assert derive_problem_verdict(decision)[0] == "solved_positive"
    assert validate_resolution(decision) == []
