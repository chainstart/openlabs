from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.provenance import fingerprint, sha256_file  # noqa: E402
from matfactory import research_publication as module  # noqa: E402
from matfactory.research_publication import (  # noqa: E402
    _load_branch_domain_reports,
    _plot_ensemble,
    _plot_haven,
    _plot_temperature_robustness,
    _table_ensemble,
    _table_haven,
    _table_temperature_robustness,
    build_research_publication_package,
)


def _write_fingerprinted(path: Path, payload: dict) -> dict:
    payload["report_fingerprint"] = fingerprint(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _domain_payload(set_id: str, publication_claim_gate: bool) -> dict:
    return {
        "set_id": set_id,
        "domain_gate_pass": True,
        "publication_claim_gate": publication_claim_gate,
    }


def test_branch_domain_inventory_retains_development_scope(tmp_path):
    development_path = tmp_path / "development.json"
    heldout_path = tmp_path / "heldout.json"
    _write_fingerprinted(
        development_path, _domain_payload("feasibility", False)
    )
    _write_fingerprinted(
        heldout_path, _domain_payload("publication-heldout", True)
    )
    gate = {
        "evidence": [
            {
                "kind": "domain:feasibility",
                "path": str(development_path),
                "sha256": sha256_file(development_path),
            },
            {
                "kind": "domain:publication-heldout",
                "path": str(heldout_path),
                "sha256": sha256_file(heldout_path),
            },
        ]
    }
    domain_gate = {
        "evidence": [
            {
                "kind": "domain:feasibility",
                "set_id": "feasibility",
                "publication_claim_gate": False,
            },
            {
                "kind": "domain:publication-heldout",
                "set_id": "publication-heldout",
                "publication_claim_gate": True,
            },
        ]
    }
    sources: list[tuple[str, Path, dict]] = []

    reports = _load_branch_domain_reports(gate, domain_gate, sources)

    assert set(reports) == {"feasibility", "publication-heldout"}
    assert reports["feasibility"]["publication_claim_gate"] is False
    assert len(sources) == 2

    invalid = json.loads(json.dumps(domain_gate))
    invalid["evidence"][0]["publication_claim_gate"] = True
    with pytest.raises(RuntimeError, match="frozen scope"):
        _load_branch_domain_reports(gate, invalid, [])


def _effect(*, equivalent: bool) -> dict:
    return {
        "analysis_gate_pass": True,
        "central_ratio": 1.1,
        "bootstrap": {
            "ratio_quantiles": {"0.025": 0.7, "0.5": 1.1, "0.975": 1.8}
        },
        "equivalence_interval": [0.5, 2.0],
        "equivalence_supported": equivalent,
    }


def _extended_inputs() -> dict:
    protocol = json.loads(
        (
            ROOT / "analysis/protocols/llzto_publication_package_v1.json"
        ).read_text(encoding="utf-8")
    )
    temperature_result = {
        "analysis_gate_pass": True,
        "primary_v1_association_supported": True,
        "categorical_temperature_robustness_supported": False,
        "association_retained_after_temperature_robustness": False,
        "holm_adjusted_p_value": 0.2,
        "categorical_temperature_fit": {
            "descriptor_coefficient_per_original_sample_sd": 0.75
        },
        "cluster_bootstrap": {
            "quantiles": {"0.025": -0.2, "0.5": 0.7, "0.975": 1.3}
        },
        "leave_one_occupancy_out": {"sign_stable": True},
        "claim_disposition": (
            "temperature_model_sensitive_downgrade_to_not_supported"
        ),
    }
    haven_records = [
        {
            "group_id": f"formal-occ0{occupancy}",
            "occupancy_seed": occupancy,
            "velocity_seed": occupancy + 1,
            "temperature_k": temperature,
            "resolved": True,
            "collective_to_tracer_ratio": 1.4 + 0.1 * occupancy,
            "stderr_cm2_s": 0.1,
        }
        for occupancy in range(2)
        for temperature in (700, 800)
    ]
    return {
        "protocol": protocol,
        "reports": {
            "ensemble_sensitivity": {
                "temperature_k": 800,
                "effects": {
                    "tracer": _effect(equivalent=True),
                    "collective": _effect(equivalent=False),
                    "collective_to_tracer_ratio": _effect(equivalent=True),
                },
                "nve_stability": {
                    "total_energy_drift_mev_atom_ps": 0.03,
                    "temperature_mean_k": 798.0,
                    "checks": {"energy_drift_within_limit": True},
                    "stability_gate_pass": True,
                },
                "ensemble_robustness_gate_pass": False,
            },
            "mechanism_temperature_robustness": {
                "analysis": {
                    "associations": {
                        "log_tracer_diffusivity": {
                            "log_jump_rate": temperature_result
                        }
                    }
                }
            },
            "haven_validation": {
                "analysis_records": haven_records,
                "prediction_at_experimental_temperature": {
                    "temperature_k": 298,
                    "is_extrapolation": True,
                    "new_configuration_collective_to_tracer_quantiles": {
                        "0.025": 0.8,
                        "0.5": 1.5,
                        "0.975": 2.7,
                    },
                    "new_configuration_haven_Dtracer_over_Dsigma_quantiles": {
                        "0.025": 0.37,
                        "0.5": 0.67,
                        "0.975": 1.25,
                    },
                },
                "experimental_comparison": {
                    "collective_to_tracer_prediction_interval": [0.8, 2.7],
                    "transformed_experimental_collective_to_tracer": 2.5,
                    "haven_prediction_interval_Dtracer_over_Dsigma": [0.37, 1.25],
                    "reported_experimental_haven_Dtracer_over_Dsigma": 0.4,
                    "compatible_with_new_configuration_prediction": True,
                },
                "benchmark": {"reported_definition": "D_tracer/D_sigma"},
                "convention_mapping": {"reciprocal_relation": "H_R = 1/R_sigma"},
            },
        },
    }


def test_extended_tables_retain_negative_outcomes_and_exact_robustness_fields():
    inputs = _extended_inputs()

    ensemble = _table_ensemble(inputs)
    temperature = _table_temperature_robustness(inputs)
    haven = _table_haven(inputs)

    collective = next(row for row in ensemble if row.get("estimator") == "collective")
    assert collective["equivalence_supported"] is False
    assert temperature[0]["coefficient_per_original_sample_sd"] == 0.75
    assert temperature[0]["cluster_bootstrap_interval"]["0.025"] == -0.2
    assert temperature[0]["association_retained_after_temperature_robustness"] is False
    assert haven[-1]["compatible_with_new_configuration_prediction"] is True
    assert haven[-1]["reciprocal_relation"] == "H_R = 1/R_sigma"


def test_extended_figures_render_complete_negative_outcomes():
    inputs = _extended_inputs()
    figures = [
        _plot_ensemble(inputs),
        _plot_temperature_robustness(inputs),
        _plot_haven(inputs),
    ]
    try:
        assert [len(figure.axes) for figure in figures] == [2, 1, 2]
    finally:
        for figure in figures:
            plt.close(figure)


def test_manifest_gate_tracks_completeness_not_scientific_equivalence(
    tmp_path, monkeypatch
):
    protocol_path = tmp_path / "publication.json"
    manifest_path = tmp_path / "artifact-manifest.json"
    protocol_path.write_text("{}", encoding="utf-8")
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    protocol = {
        "output": {
            "artifact_manifest": str(manifest_path),
            "table_formats": ["json"],
            "figure_formats": ["svg"],
        },
        "tables": [{"table_id": f"table-{index}"} for index in range(12)],
        "figures": [{"figure_id": f"figure-{index}"} for index in range(12)],
    }
    reports = {
        "analysis_manifest": {
            "model_branch_isolation": True,
            "analysis_completeness_gate_pass": True,
            "claim_narrowing_flags": {
                "size_or_volume_non_equivalence": True,
                "production_ensemble_non_equivalence": True,
                "experimental_haven_incompatibility": True,
            },
        },
        "exclusion_ledger": {"entries": [{"id": index} for index in range(10)]},
        "transport_sensitivity": {"sensitivity_gate_pass": False},
        "ensemble_sensitivity": {"ensemble_robustness_gate_pass": False},
        "mechanism_association": {"analysis": {"association_support_count": 0}},
        "mechanism_temperature_robustness": {
            "analysis": {"retained_association_count": 0}
        },
        "haven_validation": {
            "experimental_comparison": {
                "compatible_with_new_configuration_prediction": False
            }
        },
        "experimental_validation": {
            "comparisons": [
                {"compatible_with_simulation_prediction": True},
                {"compatible_with_simulation_prediction": False},
            ]
        },
    }
    inputs = {
        "protocol": protocol,
        "protocol_path": protocol_path,
        "branch": "universal",
        "reports": reports,
        "source_manifest": [
            {"path": str(source), "sha256": sha256_file(source)}
        ],
    }
    monkeypatch.setattr(module, "load_research_publication_inputs", lambda _: inputs)
    monkeypatch.setattr(module.base, "_preflight_outputs", lambda _: None)
    monkeypatch.setattr(
        module.base,
        "build_publication_tables",
        lambda _: [{"outputs": []} for _ in range(12)],
    )
    monkeypatch.setattr(
        module.base,
        "build_publication_figures",
        lambda *_args, **_kwargs: [{"outputs": []} for _ in range(12)],
    )
    monkeypatch.setattr(module.base, "_verify_output_entries", lambda *_: True)

    manifest = build_research_publication_package(protocol_path)

    assert manifest["manifest_gate_pass"] is True
    assert manifest["scientific_outcome_flags"][
        "size_volume_robustness_supported"
    ] is False
    assert manifest["scientific_outcome_flags"][
        "production_ensemble_robustness_supported"
    ] is False
    assert manifest["scientific_outcome_flags"][
        "haven_experimental_compatibility"
    ] is False
    assert manifest_path.is_file()
