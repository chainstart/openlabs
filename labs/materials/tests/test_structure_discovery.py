from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.structure_discovery import (
    build_discovery_audit,
    load_discovery_protocol,
    run_discovery_audit,
)

PILOT = ROOT / "protocols/hidden_order_soft_mode_pilot_v1.json"


def test_frozen_pilot_routes_average_disorder_without_starting_gpu():
    report = build_discovery_audit(PILOT)
    by_id = {item["candidate_id"]: item for item in report["candidates"]}

    average = by_id["cod-1545083-average"]
    assert average["route"] == "constrained-hidden-order"
    assert average["occupational_disorder"]["n_disordered_sites"] == 136
    assert average["occupational_disorder"]["n_mixed_species_sites"] == 16
    assert (
        average["occupational_disorder"][
            "minimum_rationalized_occupancy_denominator_lcm"
        ]
        == 8
    )
    assert average["composition_check"][
        "maximum_absolute_error_atoms"
    ] == pytest.approx(0.64)
    assert average["scientific_warnings"]
    assert not average["blockers"]

    ordered = by_id["llzto-occ00-ordered-reference"]
    assert ordered["route"] == "ordered-reference-only"
    assert ordered["structure"]["is_ordered"]
    assert ordered["structure"]["expected_ordered_atom_count"] == 188

    assert report["execution"]["gpu_work_started"] is False
    assert report["budget"]["authorized_gpu_hours_now"] == 0
    assert report["budget"]["planned_downstream_within_gpu_budget"]
    assert report["publication_assessment"]["potential_paper_result_available"] is False


def test_one_day_protocol_rejects_more_than_24_hours(tmp_path):
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    payload["budget"]["wall_time_hours"] = 25
    path = tmp_path / "too-long.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot exceed 24"):
        load_discovery_protocol(path)


def test_unimplemented_heavy_stage_cannot_be_enabled(tmp_path):
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    payload["stages"]["dual_model_relaxation"]["enabled"] = True
    path = tmp_path / "unsafe-stage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="only executes structure_audit"):
        load_discovery_protocol(path)


def test_audit_is_idempotent_and_refuses_changed_inputs(tmp_path):
    structure = tmp_path / "average.cif"
    shutil.copyfile(ROOT / "data/structures/raw/cod_1545083.cif", structure)
    payload = json.loads(PILOT.read_text(encoding="utf-8"))
    payload["study_id"] = "immutable-test"
    payload["root_dir"] = str(tmp_path / "run")
    payload["candidates"] = [payload["candidates"][0]]
    payload["candidates"][0]["path"] = str(structure)
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps(payload), encoding="utf-8")

    first = run_discovery_audit(protocol)
    second = run_discovery_audit(protocol)
    assert second["report_fingerprint"] == first["report_fingerprint"]
    assert (tmp_path / "run/audit.md").is_file()

    structure.write_text(structure.read_text(encoding="utf-8") + "\n# changed\n")
    with pytest.raises(RuntimeError, match="provenance changed"):
        run_discovery_audit(protocol)
