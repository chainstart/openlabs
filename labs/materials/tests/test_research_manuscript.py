from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.research_manuscript import (  # noqa: E402
    render_research_manuscript_documents,
    summarize_research_outcomes,
    validate_research_manuscript_documents,
)


def _tables() -> dict[str, list[dict]]:
    table_ids = [
        "table01-provenance",
        "table02-dft-convergence",
        "table03-domain-errors",
        "table04-formal-transport-points",
        "table05-hierarchical-arrhenius",
        "table06-replication-and-sensitivity",
        "table07-mechanism-descriptors",
        "table08-mechanism-associations",
        "table09-experiment-and-exclusions",
        "table10-production-ensemble",
        "table11-temperature-robustness",
        "table12-haven-convention",
    ]
    tables = {table_id: [] for table_id in table_ids}
    metrics = {
        "n_snapshots": 30,
        "centered_energy_mae_ev_atom": 0.01,
        "centered_energy_rmse_ev_atom": 0.012,
        "force_component_mae_ev_angstrom": 0.08,
        "force_component_rmse_ev_angstrom": 0.15,
        "stress_component_mae_gpa": 0.2,
    }
    tables["table03-domain-errors"] = [
        {
            "set_id": "fine-tuned-publication-heldout",
            "group_kind": "aggregate",
            "metric": name,
            "value": value,
            "publication_claim_gate": True,
            "domain_gate_pass": True,
        }
        for name, value in metrics.items()
    ]
    tables["table04-formal-transport-points"] = [
        {
            "run_id": f"formal-occ0{index // 5}-vel1701",
            "temperature_k": 700 + 50 * (index % 5),
            "tracer_diffusivity_cm2_s": 1e-7 * (index + 1),
            "collective_diffusivity_cm2_s": 1.5e-7 * (index + 1),
            "collective_to_tracer_ratio": 1.5,
            "tracer_resolved": True,
            "collective_resolved": True,
        }
        for index in range(25)
    ]
    activation_rows = []
    prediction_rows = []
    for estimator in ("tracer", "collective"):
        activation_rows.append(
            {
                "row_type": "activation_energy_population",
                "estimator": estimator,
                "activation_energy_ev": 0.35,
                "confidence_interval": [0.3, 0.4],
                "prediction_interval": [0.25, 0.45],
                "i2_fraction": 0.25,
            }
        )
        prediction_rows.append(
            {
                "row_type": "temperature_prediction",
                "estimator": estimator,
                "temperature_k": 300,
                "is_extrapolation": True,
                "new_configuration_predictive": {
                    "diffusivity_cm2_s_quantiles": {
                        "0.025": 1e-12,
                        "0.5": 2e-12,
                        "0.975": 4e-12,
                    }
                },
            }
        )
    tables["table05-hierarchical-arrhenius"] = activation_rows + prediction_rows
    tables["table07-mechanism-descriptors"] = [
        {
            "run_id": f"formal-{index}",
            "occupancy_seed": index // 5,
            "temperature_k": 700 + 50 * (index % 5),
            "mechanism_qualification": {
                "cooperative_string_claim_supported_across_grid": False
            },
        }
        for index in range(25)
    ]
    tables["table08-mechanism-associations"] = [
        {
            "response": f"response-{index // 4}",
            "descriptor": f"descriptor-{index % 4}",
            "analysis_gate_pass": True,
            "association_supported": False,
            "holm_adjusted_p_value": 1.0,
        }
        for index in range(12)
    ]
    tables["table09-experiment-and-exclusions"] = [
        {
            "row_type": "experimental_comparison",
            "record_id": f"experiment-{index}",
            "compatible_with_simulation_prediction": index < 4,
        }
        for index in range(9)
    ] + [
        {
            "row_type": "exclusion_or_negative_result",
            "entry_id": f"excluded-{index}",
            "disposition": "excluded",
            "scope": "synthetic",
            "reason": "synthetic retained audit row",
            "identifiers": {},
            "artifacts": [],
        }
        for index in range(10)
    ]
    tables["table10-production-ensemble"] = [
        {
            "row_type": "nve_over_nvt_effect",
            "estimator": "tracer",
            "equivalence_supported": False,
            "analysis_gate_pass": True,
        }
    ]
    tables["table11-temperature-robustness"] = [
        {
            "response": f"response-{index // 4}",
            "descriptor": f"descriptor-{index % 4}",
            "analysis_gate_pass": True,
            "primary_association_supported": False,
            "association_retained_after_temperature_robustness": False,
        }
        for index in range(12)
    ]
    tables["table12-haven-convention"] = [
        {
            "row_type": "experimental_prediction",
            "compatible_with_new_configuration_prediction": False,
        }
    ]
    return tables


def _protocol() -> dict:
    return {
        "branch": "finetuned",
        "model_branch": {"training_records": 62, "fresh_heldout_records": 30},
        "references": [
            {
                "citation": "Synthetic reference.",
                "doi": "10.0000/synthetic",
            }
        ],
        "canonical_locations": {
            "tables": "runs/tables",
            "figures": "runs/figures",
            "formal_campaign": "runs/formal",
            "mechanisms": "runs/mechanisms",
            "publication_manifest": "runs/publication.json",
            "manuscript_manifest": "runs/manuscript.json",
            "evidence_audit": "runs/audit.json",
            "readiness": "runs/readiness.json",
        },
        "reproduction_commands": ["uv run pytest -q"],
        "documents": {
            "main": {
                "minimum_bytes": 100,
                "required_sections": [
                    "Abstract",
                    "Introduction",
                    "Methods",
                    "Results",
                    "Discussion",
                    "Conclusions",
                    "Data and code availability",
                    "References",
                ],
            },
            "supplement": {
                "minimum_bytes": 100,
                "required_sections": [
                    "Supplementary methods",
                    "Numerical convergence",
                    "Potential-domain validation",
                    "All formal transport points",
                    "Hierarchical transport inference",
                    "Replication, finite-size, volume, and ensemble sensitivity",
                    "Mechanism descriptors and associations",
                    "Categorical-temperature robustness",
                    "Haven convention and experimental comparisons",
                    "Exclusions and retained negative results",
                    "Artifact inventory",
                ],
            },
            "data_availability": {
                "minimum_bytes": 100,
                "required_sections": [
                    "Data availability",
                    "Code and computational environment",
                    "Reproduction commands",
                    "Licensing boundary",
                ],
            },
        },
        "prohibited_tokens": ["TODO", "TBD", "PLACEHOLDER"],
    }


def _manifest() -> dict:
    return {
        "branch": "finetuned",
        "figures": [
            {
                "figure_id": f"fig{index:02d}-synthetic",
                "outputs": [
                    {"format": "svg", "sha256": f"figure-{index}"}
                ],
            }
            for index in range(1, 13)
        ],
        "tables": [
            {
                "table_id": f"table{index:02d}-synthetic",
                "outputs": [
                    {"format": "json", "sha256": f"table-{index}"}
                ],
            }
            for index in range(1, 13)
        ],
        "scientific_outcome_flags": {
            "size_volume_robustness_supported": False,
            "production_ensemble_robustness_supported": False,
            "haven_experimental_compatibility": False,
        },
    }


def test_finetuned_manuscript_retains_complete_negative_outcomes():
    protocol = _protocol()
    tables = _tables()
    manifest = _manifest()

    summary = summarize_research_outcomes(protocol, tables, manifest)
    documents = render_research_manuscript_documents(protocol, tables, manifest)
    checks = validate_research_manuscript_documents(
        protocol, documents, manifest
    )

    assert summary["branch"] == "finetuned"
    assert len(summary["domains"]) == 1
    assert summary["compatible_experiments"] == 4
    assert summary["incompatible_experiments"] == 5
    assert summary["primary_supported"] == []
    assert summary["temperature_retained"] == []
    assert "universal-domain test failed" in documents["main"]
    assert "non-equivalent" in documents["main"]
    assert "does not establish a causal" in documents["main"]
    assert all(checks.values()), [name for name, value in checks.items() if not value]
