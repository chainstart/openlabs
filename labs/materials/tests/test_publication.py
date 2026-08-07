from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.publication import (  # noqa: E402
    _FIGURE_BUILDERS,
    _TABLE_BUILDERS,
    _plot_workflow,
    _verify_output_entries,
    save_figure,
    write_table,
)
from matfactory import manuscript as manuscript_module  # noqa: E402
from matfactory.manuscript import (  # noqa: E402
    _table_rows as manuscript_table_rows,
    build_manuscript_package,
    render_manuscript_documents,
    validate_rendered_documents,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _domain_report(tmp_path: Path, set_id: str) -> dict:
    sources = []
    snapshot_errors = []
    for index in range(2):
        dft_path = tmp_path / f"{set_id}-{index}-dft.json"
        model_path = tmp_path / f"{set_id}-{index}-model.json"
        forces = np.asarray([[0.1 + index, -0.2, 0.3], [0.2, 0.1, -0.1]])
        stress = np.eye(3) * (0.5 + index)
        dft_path.write_text(
            json.dumps(
                {
                    "result": {
                        "total_energy_ev": -20.0 - index,
                        "forces_ev_angstrom": forces.tolist(),
                        "stress_gpa": stress.tolist(),
                    }
                }
            )
        )
        model_path.write_text(
            json.dumps(
                {
                    "result": {
                        "total_energy_ev": -19.99 - index,
                        "forces_ev_angstrom": (forces + 0.01).tolist(),
                        "stress_gpa": (stress + 0.02).tolist(),
                    }
                }
            )
        )
        sources.append(
            {
                "dft_label_path": str(dft_path),
                "model_label_path": str(model_path),
            }
        )
        snapshot_errors.append(
            {
                "snapshot_id": f"{set_id}-{index}",
                "temperature_k": 700 + 100 * index,
                "occupancy_seed": index,
                "n_snapshots": 1,
                "force_component_max_abs_ev_angstrom": 0.01,
            }
        )
    aggregate_metrics = {
        "n_snapshots": 2,
        "centered_energy_mae_ev_atom": 0.002,
        "centered_energy_rmse_ev_atom": 0.003,
        "relative_energy_spearman": 1.0,
        "force_component_mae_ev_angstrom": 0.01,
        "force_component_rmse_ev_angstrom": 0.02,
        "force_component_p95_abs_ev_angstrom": 0.03,
        "force_vector_mae_ev_angstrom": 0.02,
        "force_vector_rmse_ev_angstrom": 0.03,
        "stress_component_mae_gpa": 0.02,
        "stress_component_rmse_gpa": 0.03,
        "element_resolved_forces": {
            "Li": {
                "n_atoms": 4,
                "component_mae_ev_angstrom": 0.01,
                "component_rmse_ev_angstrom": 0.02,
                "vector_mae_ev_angstrom": 0.03,
            }
        },
    }
    stratum = {
        "n_snapshots": 1,
        "force_component_mae_ev_angstrom": 0.01,
        "force_component_rmse_ev_angstrom": 0.02,
        "force_component_max_abs_ev_angstrom": 0.03,
        "stress_component_mae_gpa": 0.02,
        "stress_component_max_abs_mean_bias_gpa": 0.02,
        "centered_energy_mae_ev_atom": 0.0,
    }
    return {
        "set_id": set_id,
        "n_snapshots": 2,
        "publication_claim_gate": set_id == "publication-heldout",
        "domain_gate_pass": True,
        "aggregate": {"metrics": aggregate_metrics},
        "temperature_strata": {"700": stratum, "800": stratum},
        "occupancy_strata": {"0": stratum, "1": stratum},
        "snapshot_errors": snapshot_errors,
        "sources": sources,
    }


def _effect(center: float = 1.1) -> dict:
    return {
        "analysis_gate_pass": True,
        "central_ratio": center,
        "equivalence_supported": True,
        "equivalence_ratio_margin": 2.0,
        "bootstrap": {
            "ratio_quantiles": {"0.025": center * 0.8, "0.5": center, "0.975": center * 1.2}
        },
    }


def _synthetic_inputs(tmp_path: Path) -> dict:
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_publication_package_v1.json").read_text()
    )
    convergence = tmp_path / "convergence.json"
    convergence.write_text(
        json.dumps(
            {
                "metrics": {
                    "max_pairwise_relative_energy_change_mev_atom": 0.1,
                    "force_component_max_abs_change_ev_angstrom": 0.002,
                    "stress_component_max_abs_change_gpa": 0.02,
                },
                "limits": {
                    "max_pairwise_relative_energy_change_mev_atom": 1.0,
                    "force_component_max_abs_change_ev_angstrom": 0.01,
                    "stress_component_max_abs_change_gpa": 0.1,
                },
                "numerically_converged": True,
            }
        )
    )
    decisions = {}
    for stage in ("cutoff", "kpoint", "scf"):
        decisions[f"{stage}_decision"] = {
            "stage": stage,
            "selected_comparison_index": 0,
            "comparisons": [
                {
                    "index": 0,
                    "passed": True,
                    "lower_settings": {"label": "lower"},
                    "upper_settings": {"label": "upper"},
                    "report_path": str(convergence),
                    "report_sha256": "hash",
                    "metrics": json.loads(convergence.read_text())["metrics"],
                }
            ],
        }
    groups = [f"formal-occ0{index}-vel{index + 1}701" for index in range(5)]
    temperatures = [700, 750, 800, 850, 900]
    analysis_records = []
    transports = {}
    mechanisms = {}
    for group_index, group in enumerate(groups):
        for temperature in temperatures:
            tracer = 1e-6 * math.exp((temperature - 700) / 200) * (1 + 0.1 * group_index)
            collective = 1.5 * tracer
            cell = f"{group}/T{temperature}"
            analysis_records.append(
                {
                    "group_id": group,
                    "occupancy_seed": group_index,
                    "temperature_k": temperature,
                    "volume_mean_angstrom3": 1100 + group_index,
                    "responses": {
                        "log_tracer_diffusivity": {"value": math.log(tracer), "variance": 0.01},
                        "log_collective_diffusivity": {"value": math.log(collective), "variance": 0.02},
                        "log_collective_to_tracer_ratio": {"value": math.log(1.5), "variance": 0.03},
                    },
                    "response_errors": {},
                    "primary_descriptors": {
                        "log_jump_rate": -2 + temperature / 1000 + 0.1 * group_index,
                        "tetrahedral_population_fraction": 0.4 + 0.01 * group_index,
                        "reverse_pair_fraction": 0.3 + 0.02 * group_index,
                        "string_excess": 0.02 * group_index - 0.01,
                    },
                    "mechanism_qualification": {
                        "cooperative_string_claim_supported_across_grid": False
                    },
                }
            )
            time = np.geomspace(0.1, 200, 30)
            transports[cell] = {
                "resolved_after_all_checks": True,
                "collective_resolved_after_all_checks": True,
                "transport": {
                    "tracer": {
                        "diffusivity_cm2_s": tracer,
                        "diffusivity_stderr_cm2_s": tracer * 0.1,
                        "r2": 0.99,
                        "diffusive_exponent": 1.0,
                        "fit_start_ps": 40,
                        "fit_end_ps": 160,
                    },
                    "collective": {
                        "diffusivity_cm2_s": collective,
                        "diffusivity_stderr_cm2_s": collective * 0.12,
                        "r2": 0.98,
                        "diffusive_exponent": 1.02,
                        "fit_start_ps": 40,
                        "fit_end_ps": 160,
                    },
                    "collective_to_tracer_ratio": 1.5,
                    "final_tracer_msd_a2": 40.0,
                    "final_collective_msd_a2": 60.0,
                    "curve": {
                        "times_ps": time.tolist(),
                        "tracer_msd_a2": (0.2 * time).tolist(),
                        "collective_msd_a2": (0.3 * time).tolist(),
                    },
                },
                "trajectory_diagnostics": {
                    "temperature_mean_k": temperature,
                    "temperature_std_k": 50,
                    "volume_mean_angstrom3": 1100 + group_index,
                    "minimum_distance_angstrom": 1.5,
                },
                "protocol_fingerprint": "formal",
            }
            mechanisms[cell] = {
                "analysis_settings": {"string_windows_ps": [0.2, 0.4, 0.8]},
                "strings": {
                    "0.4": {
                        "observed_minus_null_mean": 0.01,
                        "empirical_upper_tail_p": 0.2,
                    }
                },
                "n_jumps": 100,
                "mean_mobile_population_by_site_type": {
                    "tetrahedral-24d": 10,
                    "octahedral-96h-pair": 16,
                },
                "dwell_summary_by_site_type": {},
                "transition_counts": {},
                "reverse_jumps": {"reverse_pair_fraction": 0.3},
            }
    fits = [
        {
            "group_id": group,
            "activation_energy_ev": 0.35,
            "activation_energy_stderr_ev": 0.02,
            "log_prefactor_cm2_s": -4.0,
        }
        for group in groups
    ]
    prediction = {
        "is_extrapolation": True,
        "new_configuration_predictive": {
            "diffusivity_cm2_s_quantiles": {"0.025": 1e-9, "0.5": 2e-9, "0.975": 4e-9}
        },
        "population_geometric_mean": {
            "diffusivity_cm2_s_quantiles": {"0.025": 1.5e-9, "0.5": 2e-9, "0.975": 3e-9}
        },
    }
    estimator_report = {
        "configuration_fits": fits,
        "activation_energy_random_effects": {
            "mean": 0.35,
            "confidence_interval": [0.3, 0.4],
            "prediction_interval": [0.25, 0.45],
            "between_configuration_variance_tau2": 0.001,
            "i2_fraction": 0.4,
            "method": "REML_modified_Hartung-Knapp",
        },
        "nested_configuration_bootstrap": {"temperature_predictions": {"300": prediction}},
        "non_arrhenius_diagnostic": {
            "linear_minus_quadratic_aicc": -1.0,
            "quadratic_coefficient": 0.0,
            "quadratic_coefficient_bootstrap_interval": [-0.1, 0.1],
            "non_arrhenius_supported": False,
        },
    }
    velocity_records = []
    for occupancy in range(5):
        for velocity in range(3):
            velocity_records.append(
                {
                    "run_id": f"velocity-{occupancy}-{velocity}",
                    "occupancy_seed": occupancy,
                    "velocity_seed": occupancy * 10 + velocity,
                    "estimators": {
                        "tracer": {"value": 1e-6 * (1 + 0.1 * occupancy + 0.02 * velocity), "resolved": True},
                        "collective": {"value": 1.5e-6 * (1 + 0.1 * occupancy + 0.02 * velocity), "resolved": True},
                        "collective_to_tracer_ratio": {"value": 1.5 + 0.01 * velocity, "resolved": True},
                    },
                }
            )
    association_results = {}
    for response in (
        "log_tracer_diffusivity",
        "log_collective_diffusivity",
        "log_collective_to_tracer_ratio",
    ):
        association_results[response] = {}
        for descriptor in (
            "log_jump_rate",
            "tetrahedral_population_fraction",
            "reverse_pair_fraction",
            "string_excess",
        ):
            association_results[response][descriptor] = {
                "analysis_gate_pass": True,
                "holm_adjusted_p_value": 0.2,
                "association_supported": False,
                "primary_fit": {
                    "descriptor_coefficient_per_sample_sd": 0.1,
                    "partial_weighted_r2": 0.05,
                },
                "permutation_test": {"two_sided_p_value": 0.1},
                "cluster_bootstrap": {
                    "quantiles": {"0.025": -0.1, "0.5": 0.1, "0.975": 0.3},
                    "interval_excludes_zero": False,
                },
                "leave_one_occupancy_out": {"sign_stable": True},
                "mechanism_setting_sensitivity": {"sign_stable": True, "slope_range": [0.05, 0.15]},
            }
    estimators_effect = {
        "tracer": _effect(),
        "collective": _effect(1.2),
        "collective_to_tracer_ratio": _effect(1.05),
    }
    validation = []
    for index in range(9):
        validation.append(
            {
                "status": "evaluated",
                "record_id": f"experiment-{index}",
                "property": "activation_energy" if index % 3 == 0 else "tracer_diffusivity",
                "temperature_k": None if index % 3 == 0 else 298.0,
                "observed": 0.35 if index % 3 == 0 else 2e-13,
                "predicted_population_median": 0.36 if index % 3 == 0 else 2.2e-13,
                "new_configuration_prediction_interval": {
                    "lower": 0.25 if index % 3 == 0 else 1e-13,
                    "median": 0.36 if index % 3 == 0 else 2.2e-13,
                    "upper": 0.45 if index % 3 == 0 else 4e-13,
                },
                "benchmark_role": "secondary_derived_comparator" if index == 8 else "primary_direct_measurement",
                "compatible_with_simulation_prediction": True,
            }
        )
    reports = {
        **decisions,
        "mpi_report": {
            "comparisons": [
                {
                    "structure_id": "relaxed",
                    "baseline_mpi_ranks": 1,
                    "comparison_mpi_ranks": 8,
                    "energy_abs_change_mev_atom": 1e-5,
                    "force_component_max_abs_change_ev_angstrom": 1e-7,
                    "stress_component_max_abs_change_gpa": 1e-7,
                }
            ],
            "metrics": {
                "energy_abs_change_mev_atom_max": 1e-5,
                "force_component_max_abs_change_ev_angstrom": 1e-7,
                "stress_component_max_abs_change_gpa": 1e-7,
            },
            "limits": {
                "energy_abs_change_mev_atom_max": 0.001,
                "force_component_max_abs_change_ev_angstrom": 1e-5,
                "stress_component_max_abs_change_gpa": 1e-5,
            },
            "mpi_equivalence_gate_pass": True,
        },
        "hierarchical_transport": {"estimators": {"tracer": estimator_report, "collective": estimator_report}},
        "nested_velocity": {
            "records": velocity_records,
            "result": {
                "estimators": {
                    name: {
                        "analysis_gate_pass": True,
                        "occupancy_variance_log_scale": 0.04,
                        "velocity_variance_log_scale": 0.01,
                    }
                    for name in ("tracer", "collective", "collective_to_tracer_ratio")
                }
            },
        },
        "transport_sensitivity": {
            "finite_size": {"temperature_k": 800, "estimators": estimators_effect},
            "fixed_experimental_volume": {"temperature_k": 800, "estimators": estimators_effect},
            "npt_volume": {
                "by_temperature": [
                    {"temperature_k": temperature, "estimators": estimators_effect}
                    for temperature in temperatures
                ],
                "activation_energy_difference": {},
            },
        },
        "mechanism_association": {
            "analysis_records": analysis_records,
            "analysis": {"associations": association_results},
        },
        "experimental_validation": {"comparisons": validation},
        "exclusion_ledger": {
            "entries": [
                {
                    "entry_id": f"excluded-{index}",
                    "disposition": "excluded",
                    "scope": "test",
                    "reason": "test",
                    "artifacts": [],
                }
                for index in range(10)
            ]
        },
    }
    return {
        "protocol": protocol,
        "reports": reports,
        "domain_reports": {
            "feasibility": _domain_report(tmp_path, "feasibility"),
            "publication-heldout": _domain_report(tmp_path, "publication-heldout"),
        },
        "transports": transports,
        "mechanisms": mechanisms,
        "source_manifest": [{"source_id": "synthetic", "path": str(convergence), "sha256": "hash"}],
    }


def test_all_frozen_table_and_figure_builders_accept_complete_synthetic_inputs(tmp_path):
    inputs = _synthetic_inputs(tmp_path)
    assert len(_TABLE_BUILDERS) == 9
    for table_id, builder in _TABLE_BUILDERS.items():
        rows = builder(inputs)
        assert rows, table_id
    import matplotlib.pyplot as plt

    assert len(_FIGURE_BUILDERS) == 8
    for figure_id, builder in _FIGURE_BUILDERS.items():
        figure = builder(inputs)
        assert figure.axes, figure_id
        plt.close(figure)
    workflow = _plot_workflow(inputs, package_outputs_complete=True)
    assert workflow.axes
    plt.close(workflow)


def test_table_and_figure_outputs_are_hashed_and_immutable(tmp_path):
    table = write_table("table-test", "Test", [{"a": 1, "nested": {"b": 2}}], tmp_path)
    assert _verify_output_entries([table], ["csv", "json"])
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        write_table("table-test", "Test", [{"a": 1}], tmp_path)

    import matplotlib.pyplot as plt

    figure, axis = plt.subplots()
    axis.plot([0, 1], [0, 1])
    saved = save_figure(
        figure,
        "figure-test",
        "Test",
        tmp_path,
        formats=["svg", "pdf", "png"],
        png_dpi=100,
    )
    plt.close(figure)
    assert _verify_output_entries([saved], ["svg", "pdf", "png"])


def _synthetic_manuscript_inputs(tmp_path: Path) -> dict:
    inputs = _synthetic_inputs(tmp_path)
    for result in inputs["reports"]["nested_velocity"]["result"]["estimators"].values():
        result["occupancy_variance_boundary_test"] = {"p_value": 0.03}
    return inputs


def _synthetic_publication_manifest(
    tmp_path: Path, inputs: dict, tables: dict[str, list[dict]]
) -> dict:
    source = tmp_path / "publication-source.json"
    source.write_text("{}\n")
    figures = []
    for specification in inputs["protocol"]["figures"]:
        outputs = []
        for format_name in ("svg", "pdf", "png"):
            path = tmp_path / f"{specification['figure_id']}.{format_name}"
            path.write_text(f"{specification['figure_id']} {format_name}\n")
            outputs.append(
                {
                    "format": format_name,
                    "path": str(path),
                    "sha256": sha256_file(path),
                }
            )
        figures.append({**specification, "outputs": outputs})
    table_outputs = []
    for specification in inputs["protocol"]["tables"]:
        outputs = []
        for format_name in ("csv", "json"):
            path = tmp_path / f"{specification['table_id']}.{format_name}"
            path.write_text(f"{specification['table_id']} {format_name}\n")
            outputs.append(
                {
                    "format": format_name,
                    "path": str(path),
                    "sha256": sha256_file(path),
                }
            )
        table_outputs.append(
            {
                **specification,
                "n_rows": len(tables[specification["table_id"]]),
                "outputs": outputs,
            }
        )
    return {
        "figures": figures,
        "tables": table_outputs,
        "sources": [{"path": str(source), "sha256": sha256_file(source)}],
    }


def test_manuscript_renderer_populates_outcomes_and_all_required_sections(tmp_path):
    inputs = _synthetic_manuscript_inputs(tmp_path)
    tables = manuscript_table_rows(inputs)
    manifest = _synthetic_publication_manifest(tmp_path, inputs, tables)
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_manuscript_v1.json").read_text()
    )
    documents = render_manuscript_documents(protocol, tables, manifest)
    checks = validate_rendered_documents(protocol, documents, manifest)
    assert all(checks.values())
    assert "2.000e-09" in documents["main"]
    assert "none of the twelve preregistered" in documents["main"]
    assert "do not establish a causal" in documents["main"]


def test_manuscript_package_verifies_publication_and_is_immutable(
    tmp_path, monkeypatch
):
    inputs = _synthetic_manuscript_inputs(tmp_path)
    tables = manuscript_table_rows(inputs)
    publication_protocol = tmp_path / "publication-protocol.json"
    publication_protocol.write_text("{}\n")
    manifest = _synthetic_publication_manifest(tmp_path, inputs, tables)
    manifest.update(
        manifest_gate_pass=True,
        publication_protocol_sha256=sha256_file(publication_protocol),
    )
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    publication_manifest = tmp_path / "artifact-manifest.json"
    publication_manifest.write_text(json.dumps(manifest))

    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_manuscript_v1.json").read_text()
    )
    protocol["sources"].update(
        publication_protocol=str(publication_protocol),
        publication_protocol_sha256=sha256_file(publication_protocol),
        publication_manifest=str(publication_manifest),
    )
    protocol["output"].update(
        main=str(tmp_path / "manuscript/main.md"),
        supplement=str(tmp_path / "manuscript/supplement.md"),
        data_availability=str(tmp_path / "manuscript/data_availability.md"),
        manifest=str(tmp_path / "manuscript-manifest.json"),
    )
    protocol_path = tmp_path / "manuscript-protocol.json"
    protocol_path.write_text(json.dumps(protocol))
    monkeypatch.setattr(manuscript_module, "load_publication_inputs", lambda _: inputs)

    built = build_manuscript_package(protocol_path)
    assert built["manuscript_gate_pass"] is True
    assert built["publication_logical_output_hashes_verified"] == 45
    unsigned = dict(built)
    stored = unsigned.pop("manifest_fingerprint")
    assert stored == fingerprint(unsigned)
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        build_manuscript_package(protocol_path)
