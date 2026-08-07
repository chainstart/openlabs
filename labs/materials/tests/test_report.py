from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.report import build_campaign_report, mean_sd_ci95  # noqa: E402


def test_mean_sd_ci95_does_not_invent_single_run_uncertainty():
    summary = mean_sd_ci95([0.4])
    assert summary == {"n": 1, "mean": 0.4, "sample_sd": None, "ci95": None}


def test_mean_sd_ci95_uses_between_replicate_spread():
    summary = mean_sd_ci95([0.3, 0.4, 0.5])
    assert summary["mean"] == pytest.approx(0.4)
    assert summary["sample_sd"] == pytest.approx(0.1)
    assert summary["ci95"] > 0


def test_numerical_gate_selects_largest_passing_timestep(tmp_path):
    state = {
        "campaign_id": "c",
        "protocol_sha256": "sha",
    }
    (tmp_path / "campaign_state.json").write_text(json.dumps(state))
    for timestep, drift in ((1.0, 0.02), (2.0, 0.03)):
        run = tmp_path / f"dt{timestep:g}"
        run.mkdir()
        point = {
            "temperature": 800,
            "wall_seconds": 10,
            "production_ps": 1,
            "diffusivity_cm2_s": 1e-6,
            "diffusive_exponent": 0.5,
            "resolved": False,
            "rejection_reasons": ["short"],
        }
        result = {
            "config": {
                "protocol_tier": "numerics",
                "timestep_fs": timestep,
                "equilibration_steps": 100,
                "production_steps": 100,
                "max_abs_nve_energy_drift_mev_atom_ps": 1.0,
                "occupancy_seed": 0,
                "seed": 0,
                "primitive_cell": True,
            },
            "points": [point],
        }
        (run / "result.json").write_text(json.dumps(result))
        diagnostics = {
            "trajectory_diagnostics": {
                "total_energy_drift_mev_atom_ps": drift,
                "temperature_mean_k": 800,
                "temperature_std_k": 40,
                "minimum_distance_angstrom": 1.5,
            },
            "transport": {"collective": {"diffusive_exponent": 0.6}},
        }
        (run / "T800.transport.json").write_text(json.dumps(diagnostics))

    report = build_campaign_report(tmp_path)
    assert report["numerical_gate"]["all_energy_drift_checks_pass"]
    assert report["numerical_gate"]["selected_timestep_fs"] == 2.0
    assert not report["publication_claims_ready"]
