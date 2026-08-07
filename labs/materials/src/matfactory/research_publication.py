"""Build branch-aware LLZTO publication artifacts with extended robustness evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from . import publication as base
from .evidence_audit import validate_exclusion_ledger
from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    git_state,
    sha256_file,
)
from .research_analysis_queue import _sensitivity_analysis_complete


_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _load_report(
    value: str | Path,
    *,
    field: str | None,
    label: str,
) -> tuple[Path, dict[str, Any]]:
    path = _repo_path(value)
    payload = _read_json(path)
    if field is not None:
        _verify_fingerprint(payload, field, label)
    return path, payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _load_branch_domain_reports(
    gate: dict[str, Any],
    domain_gate: dict[str, Any],
    root_reports: list[tuple[str, Path, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    expected_evidence = {
        str(row["kind"]): {
            "set_id": str(row["set_id"]),
            "publication_claim_gate": bool(row["publication_claim_gate"]),
        }
        for row in domain_gate["evidence"]
    }
    domain_reports: dict[str, dict[str, Any]] = {}
    seen_kinds: set[str] = set()
    for evidence in gate.get("evidence", []):
        kind = str(evidence.get("kind", ""))
        if kind not in expected_evidence:
            continue
        seen_kinds.add(kind)
        set_id = expected_evidence[kind]["set_id"]
        path = _repo_path(evidence["path"])
        if sha256_file(path) != evidence["sha256"]:
            raise RuntimeError(f"G2 domain evidence hash mismatch: {path}")
        payload = _read_json(path)
        _verify_fingerprint(payload, "report_fingerprint", kind)
        _require(
            payload.get("set_id") == set_id
            and payload.get("domain_gate_pass") is True
            and payload.get("publication_claim_gate")
            is expected_evidence[kind]["publication_claim_gate"],
            f"publication requires passed domain set {set_id} with its frozen scope",
        )
        domain_reports[set_id] = payload
        root_reports.append((kind, path, payload))
    _require(
        seen_kinds == set(expected_evidence)
        and set(domain_reports)
        == {row["set_id"] for row in expected_evidence.values()},
        "publication G2 domain evidence inventory differs from its branch protocol",
    )
    return domain_reports


def load_research_publication_inputs(protocol_path: Path | str) -> dict[str, Any]:
    """Load one isolated model branch without assuming universal-domain set names."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("research publication protocol schema_version must be '1.0'")
    branch = str(protocol.get("branch", ""))
    if branch not in {"universal", "finetuned"}:
        raise ValueError("research publication branch must be universal or finetuned")
    paths = protocol["sources"]
    fingerprint_fields = {
        "cutoff_decision": "decision_fingerprint",
        "kpoint_decision": "decision_fingerprint",
        "scf_decision": "decision_fingerprint",
        "mpi_report": "report_fingerprint",
        "g2_release": "gate_fingerprint",
        "hierarchical_transport": "report_fingerprint",
        "nested_velocity": "report_fingerprint",
        "transport_sensitivity": "report_fingerprint",
        "mechanism_association": "report_fingerprint",
        "experimental_validation": "report_fingerprint",
        "ensemble_sensitivity": "report_fingerprint",
        "mechanism_temperature_robustness": "report_fingerprint",
        "haven_validation": "report_fingerprint",
        "analysis_manifest": "manifest_fingerprint",
    }
    report_names = [
        "campaign_report",
        "evidence_audit_protocol",
        *fingerprint_fields,
    ]
    reports: dict[str, dict[str, Any]] = {}
    root_reports: list[tuple[str, Path, dict[str, Any]]] = []
    report_paths: dict[str, Path] = {}
    for name in report_names:
        path, payload = _load_report(
            paths[name], field=fingerprint_fields.get(name), label=name
        )
        reports[name] = payload
        report_paths[name] = path
        root_reports.append((name, path, payload))

    analysis_manifest = reports["analysis_manifest"]
    _require(
        analysis_manifest.get("branch") == branch
        and analysis_manifest.get("analysis_completeness_gate_pass") is True
        and analysis_manifest.get("model_branch_isolation") is True,
        "publication requires one complete isolated research-analysis branch",
    )
    manifest_name_map = {
        "campaign_report": "campaign_report",
        "hierarchical_transport": "hierarchical",
        "nested_velocity": "nested_velocity",
        "transport_sensitivity": "transport_sensitivity",
        "mechanism_association": "mechanism_association",
        "experimental_validation": "experimental_validation",
        "ensemble_sensitivity": "ensemble",
        "mechanism_temperature_robustness": "mechanism_temperature",
        "haven_validation": "haven",
    }
    for source_name, manifest_name in manifest_name_map.items():
        record = analysis_manifest.get("reports", {}).get(manifest_name, {})
        _require(
            _repo_path(record.get("path", "")) == report_paths[source_name]
            and record.get("sha256") == sha256_file(report_paths[source_name])
            and record.get("complete") is True,
            f"analysis manifest does not release {source_name}",
        )

    _require(
        reports["campaign_report"].get("numerical_gate", {}).get(
            "all_energy_drift_checks_pass"
        )
        is True,
        "publication requires the branch-specific time-step stability gate",
    )
    for stage in ("cutoff", "kpoint", "scf"):
        decision = reports[f"{stage}_decision"]
        _require(
            decision.get("stage") == stage and decision.get("can_continue") is True,
            f"publication requires a passing {stage} decision",
        )
    _require(
        reports["mpi_report"].get("mpi_equivalence_gate_pass") is True,
        "publication requires MPI numerical equivalence",
    )
    gate = reports["g2_release"]
    domain_gate = protocol["domain_gate"]
    _require(
        gate.get("gate_id") == domain_gate["gate_id"]
        and gate.get("status") == "pass",
        "publication G2 release does not match its model branch",
    )
    _require(
        reports["hierarchical_transport"].get("hierarchical_gate_pass") is True,
        "publication requires complete hierarchical transport",
    )
    _require(
        reports["nested_velocity"].get("result", {}).get(
            "nested_velocity_gate_pass"
        )
        is True,
        "publication requires complete nested velocity inference",
    )
    sensitivity = reports["transport_sensitivity"]
    _require(
        _sensitivity_analysis_complete(sensitivity),
        "publication requires estimable size/volume analyses; physical "
        "non-equivalence remains publishable as a negative outcome",
    )
    association = reports["mechanism_association"]
    _require(
        association.get("input_gate_pass") is True
        and association.get("analysis", {}).get("grid_gate_pass") is True
        and len(association.get("analysis_records", [])) == 25,
        "publication requires the complete mechanism-association family",
    )
    validation = reports["experimental_validation"]
    _require(
        validation.get("n_blocked") == 0
        and validation.get("n_evaluated")
        == validation.get("n_eligible_measurements")
        == 9,
        "publication requires all nine experimental comparisons",
    )
    _require(
        reports["ensemble_sensitivity"].get(
            "analysis_completeness_gate_pass"
        )
        is True,
        "publication requires complete production-ensemble sensitivity",
    )
    _require(
        reports["mechanism_temperature_robustness"].get(
            "robustness_completeness_gate_pass"
        )
        is True,
        "publication requires complete categorical-temperature robustness",
    )
    _require(
        reports["haven_validation"].get("analysis_completeness_gate_pass")
        is True,
        "publication requires complete Haven-convention validation",
    )

    domain_reports = _load_branch_domain_reports(gate, domain_gate, root_reports)

    ledger_path = _repo_path(paths["exclusion_ledger"])
    ledger = _read_json(ledger_path)
    ledger_validation = validate_exclusion_ledger(ledger, ledger_path=ledger_path)
    _require(
        ledger_validation["ledger_gate_pass"],
        "publication exclusion ledger failed provenance validation",
    )
    reports["exclusion_ledger"] = ledger
    root_reports.append(("exclusion_ledger", ledger_path, ledger))

    campaign_root = _repo_path(paths["campaign_root"])
    mechanism_root = _repo_path(paths["mechanism_root"])
    transports: dict[str, dict[str, Any]] = {}
    mechanisms: dict[str, dict[str, Any]] = {}
    source_hashes = {
        (item.get("kind"), item.get("run_id"), item.get("temperature_k")): item
        for item in association.get("sources", [])
    }
    for row in association["analysis_records"]:
        run_id = str(row["group_id"])
        temperature = int(row["temperature_k"])
        cell = f"{run_id}/T{temperature}"
        transport_path = campaign_root / run_id / f"T{temperature}.transport.json"
        mechanism_path = mechanism_root / run_id / f"T{temperature}.json"
        transport_source = source_hashes.get(("transport", run_id, temperature))
        _require(
            isinstance(transport_source, dict)
            and transport_source.get("sha256") == sha256_file(transport_path),
            f"transport source mismatch for {cell}",
        )
        transport = _read_json(transport_path)
        _require(
            transport.get("resolved_after_all_checks") is True
            and transport.get("collective_resolved_after_all_checks") is True,
            f"unresolved formal transport point {cell}",
        )
        mechanism = _read_json(mechanism_path)
        _require(
            mechanism.get("quality_gate_pass") is True,
            f"mechanism assignment gate failed for {cell}",
        )
        trajectory_path = campaign_root / run_id / f"T{temperature}.traj"
        _require(
            mechanism.get("trajectory_sha256") == sha256_file(trajectory_path),
            f"mechanism trajectory hash mismatch for {cell}",
        )
        transports[cell] = transport
        mechanisms[cell] = mechanism
        root_reports.extend(
            [
                (f"transport:{cell}", transport_path, transport),
                (f"mechanism:{cell}", mechanism_path, mechanism),
            ]
        )
    return {
        "protocol": protocol,
        "protocol_path": source,
        "branch": branch,
        "reports": reports,
        "domain_reports": domain_reports,
        "transports": transports,
        "mechanisms": mechanisms,
        "source_manifest": base._verified_sources(root_reports),
    }


def _table_ensemble(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    report = inputs["reports"]["ensemble_sensitivity"]
    rows = []
    for estimator, effect in report["effects"].items():
        rows.append(
            {
                "row_type": "nve_over_nvt_effect",
                "estimator": estimator,
                "central_ratio": effect.get("central_ratio"),
                "ratio_quantiles": effect.get("bootstrap", {}).get(
                    "ratio_quantiles"
                ),
                "equivalence_interval": effect.get("equivalence_interval"),
                "equivalence_supported": effect.get("equivalence_supported"),
                "analysis_gate_pass": effect.get("analysis_gate_pass"),
            }
        )
    rows.append(
        {
            "row_type": "nve_stability",
            **report["nve_stability"],
            "ensemble_robustness_gate_pass": report[
                "ensemble_robustness_gate_pass"
            ],
        }
    )
    return rows


def _table_temperature_robustness(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    report = inputs["reports"]["mechanism_temperature_robustness"]
    rows = []
    for response, by_descriptor in report["analysis"]["associations"].items():
        for descriptor, result in by_descriptor.items():
            rows.append(
                {
                    "response": response,
                    "descriptor": descriptor,
                    "analysis_gate_pass": result.get("analysis_gate_pass"),
                    "primary_association_supported": result.get(
                        "primary_v1_association_supported"
                    ),
                    "categorical_temperature_robustness_supported": result.get(
                        "categorical_temperature_robustness_supported"
                    ),
                    "association_retained_after_temperature_robustness": result.get(
                        "association_retained_after_temperature_robustness"
                    ),
                    "holm_adjusted_p_value": result.get("holm_adjusted_p_value"),
                    "coefficient_per_original_sample_sd": result.get(
                        "categorical_temperature_fit", {}
                    ).get("descriptor_coefficient_per_original_sample_sd"),
                    "cluster_bootstrap_interval": result.get(
                        "cluster_bootstrap", {}
                    ).get("quantiles"),
                    "leave_one_occupancy_out_sign_stable": result.get(
                        "leave_one_occupancy_out", {}
                    ).get("sign_stable"),
                    "claim_disposition": result.get("claim_disposition"),
                }
            )
    return rows


def _table_haven(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    report = inputs["reports"]["haven_validation"]
    rows = [
        {"row_type": "trajectory_ratio", **record}
        for record in report["analysis_records"]
    ]
    rows.append(
        {
            "row_type": "experimental_prediction",
            **report["prediction_at_experimental_temperature"],
            **report["experimental_comparison"],
            "reported_definition": report["benchmark"]["reported_definition"],
            "reciprocal_relation": report["convention_mapping"][
                "reciprocal_relation"
            ],
        }
    )
    return rows


def _plot_research_domain(inputs: dict[str, Any]) -> Any:
    figure = base._plot_domain(inputs)
    if inputs["branch"] == "finetuned":
        figure.suptitle(
            "Fine-tuned CHGNet–DFT parity on the fresh publication-heldout domain"
        )
    else:
        figure.suptitle("Universal CHGNet–DFT parity on disjoint domain sets")
    figure.tight_layout()
    return figure


def _ratio_interval(effect: dict[str, Any]) -> tuple[float, float, float]:
    values = sorted(
        (float(key), float(value))
        for key, value in effect["bootstrap"]["ratio_quantiles"].items()
    )
    median = min(values, key=lambda row: abs(row[0] - 0.5))[1]
    return values[0][1], median, values[-1][1]


def _plot_ensemble(inputs: dict[str, Any]) -> Any:
    plt = base._configure_matplotlib(inputs["protocol"])
    report = inputs["reports"]["ensemble_sensitivity"]
    estimators = ["tracer", "collective", "collective_to_tracer_ratio"]
    intervals = [_ratio_interval(report["effects"][name]) for name in estimators]
    centers = np.asarray([row[1] for row in intervals])
    lower = centers - np.asarray([row[0] for row in intervals])
    upper = np.asarray([row[2] for row in intervals]) - centers
    figure, axes = plt.subplots(1, 2, figsize=(11.5, 4.1))
    colors = [
        inputs["protocol"]["style"]["equivalence_color"]
        if report["effects"][name]["equivalence_supported"]
        else inputs["protocol"]["style"]["negative_or_blocked_color"]
        for name in estimators
    ]
    axes[0].errorbar(
        np.arange(3),
        centers,
        yerr=np.vstack([lower, upper]),
        fmt="none",
        ecolor=colors,
        capsize=5,
        linewidth=1.8,
    )
    axes[0].scatter(np.arange(3), centers, c=colors, s=48, zorder=3)
    margin = float(report["effects"][estimators[0]]["equivalence_interval"][1])
    axes[0].axhspan(1.0 / margin, margin, color="#009E73", alpha=0.12)
    axes[0].axhline(1.0, color="black", linewidth=1)
    axes[0].set_xticks(
        np.arange(3), ["tracer", "collective", "collective/tracer"]
    )
    axes[0].set_ylabel("NVE / NVT ratio (95% block bootstrap)")
    axes[0].set_yscale("log")
    axes[0].grid(axis="y", alpha=0.2)
    stability = report["nve_stability"]
    values = [
        abs(float(stability["total_energy_drift_mev_atom_ps"])),
        abs(float(stability["temperature_mean_k"]) - report["temperature_k"]),
    ]
    axes[1].bar(
        ["|energy drift|\nmeV atom⁻¹ ps⁻¹", "|mean T-target|\nK"],
        values,
        color=(
            inputs["protocol"]["style"]["equivalence_color"]
            if stability["stability_gate_pass"]
            else inputs["protocol"]["style"]["negative_or_blocked_color"]
        ),
    )
    axes[1].set_title("NVE stability diagnostics")
    axes[1].grid(axis="y", alpha=0.2)
    figure.suptitle("Matched 500 ps production-ensemble sensitivity at 800 K")
    figure.tight_layout()
    return figure


def _plot_temperature_robustness(inputs: dict[str, Any]) -> Any:
    plt = base._configure_matplotlib(inputs["protocol"])
    report = inputs["reports"]["mechanism_temperature_robustness"]
    associations = report["analysis"]["associations"]
    responses = list(associations)
    descriptors = list(next(iter(associations.values())))
    values = np.zeros((len(responses), len(descriptors)))
    annotations: list[list[str]] = []
    for row_index, response in enumerate(responses):
        labels = []
        for column_index, descriptor in enumerate(descriptors):
            result = associations[response][descriptor]
            primary = result.get("primary_v1_association_supported") is True
            retained = result.get(
                "association_retained_after_temperature_robustness"
            ) is True
            values[row_index, column_index] = 2 if retained else (1 if primary else 0)
            labels.append("retained" if retained else ("downgraded" if primary else "null"))
        annotations.append(labels)
    from matplotlib.colors import ListedColormap

    figure, axis = plt.subplots(figsize=(10.0, 4.8))
    image = axis.imshow(
        values,
        cmap=ListedColormap(["#BDBDBD", "#E69F00", "#009E73"]),
        vmin=-0.5,
        vmax=2.5,
        aspect="auto",
    )
    del image
    axis.set_xticks(np.arange(len(descriptors)), descriptors, rotation=25, ha="right")
    axis.set_yticks(np.arange(len(responses)), responses)
    for i, labels in enumerate(annotations):
        for j, label in enumerate(labels):
            axis.text(j, i, label, ha="center", va="center", fontsize=7)
    axis.set_title(
        "Primary associations under arbitrary categorical temperature adjustment"
    )
    figure.tight_layout()
    return figure


def _plot_haven(inputs: dict[str, Any]) -> Any:
    plt = base._configure_matplotlib(inputs["protocol"])
    report = inputs["reports"]["haven_validation"]
    records = report["analysis_records"]
    figure, axes = plt.subplots(1, 2, figsize=(11.8, 4.4))
    for occupancy in sorted({int(row["occupancy_seed"]) for row in records}):
        selected = sorted(
            (row for row in records if int(row["occupancy_seed"]) == occupancy),
            key=lambda row: int(row["temperature_k"]),
        )
        axes[0].errorbar(
            [row["temperature_k"] for row in selected],
            [row["collective_to_tracer_ratio"] for row in selected],
            yerr=[row["stderr_cm2_s"] for row in selected],
            marker="o",
            linewidth=1,
            capsize=2,
            label=f"occupancy {occupancy}",
        )
    axes[0].set(
        xlabel="temperature (K)",
        ylabel=r"$R_\sigma=D_{collective}/D_{tracer}$",
        title="Configuration-resolved correlation factor",
    )
    axes[0].grid(alpha=0.2)
    axes[0].legend(frameon=False, fontsize=7)
    prediction = report["prediction_at_experimental_temperature"]
    ratio_quantiles = sorted(
        (float(key), float(value))
        for key, value in prediction[
            "new_configuration_collective_to_tracer_quantiles"
        ].items()
    )
    haven_quantiles = sorted(
        (float(key), float(value))
        for key, value in prediction[
            "new_configuration_haven_Dtracer_over_Dsigma_quantiles"
        ].items()
    )
    for x, quantiles, observed, label in (
        (
            0,
            ratio_quantiles,
            report["experimental_comparison"][
                "transformed_experimental_collective_to_tracer"
            ],
            "Dcollective/Dtracer",
        ),
        (
            1,
            haven_quantiles,
            report["experimental_comparison"][
                "reported_experimental_haven_Dtracer_over_Dsigma"
            ],
            "Dtracer/Dsigma",
        ),
    ):
        median = min(quantiles, key=lambda row: abs(row[0] - 0.5))[1]
        low, high = quantiles[0][1], quantiles[-1][1]
        axes[1].errorbar(
            [x],
            [median],
            yerr=[[median - low], [high - median]],
            fmt="o",
            capsize=5,
            label="simulation predictive interval" if x == 0 else None,
        )
        axes[1].scatter(
            [x], [observed], marker="x", s=65, color="#D55E00", zorder=4
        )
    axes[1].set_xticks([0, 1], ["Rσ", "HR"])
    axes[1].set_ylabel("dimensionless ratio at 298 K")
    axes[1].set_title("Reciprocal convention and experimental point")
    axes[1].grid(axis="y", alpha=0.2)
    figure.suptitle(
        "Haven convention: HR = Dtracer/Dsigma = 1/(Dcollective/Dtracer)"
    )
    figure.tight_layout()
    return figure


_EXTRA_TABLE_BUILDERS = {
    "table10-production-ensemble": _table_ensemble,
    "table11-temperature-robustness": _table_temperature_robustness,
    "table12-haven-convention": _table_haven,
}

_EXTRA_FIGURE_BUILDERS = {
    "fig10-production-ensemble": _plot_ensemble,
    "fig11-temperature-robustness": _plot_temperature_robustness,
    "fig12-haven-convention": _plot_haven,
}


def build_research_publication_package(protocol_path: Path | str) -> dict[str, Any]:
    """Generate twelve figures/tables and a branch-aware immutable manifest."""
    inputs = load_research_publication_inputs(protocol_path)
    protocol = inputs["protocol"]
    base._preflight_outputs(protocol)
    table_builders = {**base._TABLE_BUILDERS, **_EXTRA_TABLE_BUILDERS}
    figure_builders = {
        **base._FIGURE_BUILDERS,
        "fig03-chgnet-dft-domain": _plot_research_domain,
        **_EXTRA_FIGURE_BUILDERS,
    }
    with patch.dict(base._TABLE_BUILDERS, table_builders, clear=True), patch.dict(
        base._FIGURE_BUILDERS, figure_builders, clear=True
    ):
        tables = base.build_publication_tables(inputs)
        table_formats = list(protocol["output"]["table_formats"])
        tables_complete = bool(
            len(tables) == len(protocol["tables"])
            and base._verify_output_entries(tables, table_formats)
        )
        figures = base.build_publication_figures(
            inputs, package_tables_complete=tables_complete
        )
        figure_formats = list(protocol["output"]["figure_formats"])
        figures_complete = bool(
            len(figures) == len(protocol["figures"])
            and base._verify_output_entries(figures, figure_formats)
        )
    source_manifest = inputs["source_manifest"]
    sources_complete = all(
        Path(row["path"]).is_file()
        and sha256_file(row["path"]) == row["sha256"]
        for row in source_manifest
    )
    reports = inputs["reports"]
    analysis_manifest = reports["analysis_manifest"]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "llzto-research-publication-artifacts-v2",
        "branch": inputs["branch"],
        "publication_protocol_path": str(inputs["protocol_path"]),
        "publication_protocol_sha256": sha256_file(inputs["protocol_path"]),
        "generation_command": (
            "uv run python -m matfactory.research_publication --protocol "
            + str(inputs["protocol_path"])
        ),
        "sources": source_manifest,
        "figures": figures,
        "tables": tables,
        "checks": {
            "source_hashes_verified": sources_complete,
            "model_branch_isolated": analysis_manifest.get(
                "model_branch_isolation"
            )
            is True,
            "complete_research_analysis": analysis_manifest.get(
                "analysis_completeness_gate_pass"
            )
            is True,
            "all_declared_figures_generated": figures_complete,
            "all_declared_tables_generated": tables_complete,
            "figure_count": len(figures) == 12,
            "table_count": len(tables) == 12,
            "negative_and_excluded_rows_retained": len(
                reports["exclusion_ledger"]["entries"]
            )
            >= 10,
        },
        "scientific_outcome_flags": {
            "claim_narrowing_flags": analysis_manifest[
                "claim_narrowing_flags"
            ],
            "size_volume_robustness_supported": reports[
                "transport_sensitivity"
            ].get("sensitivity_gate_pass"),
            "production_ensemble_robustness_supported": reports[
                "ensemble_sensitivity"
            ].get("ensemble_robustness_gate_pass"),
            "supported_primary_mechanism_associations": reports[
                "mechanism_association"
            ]["analysis"]["association_support_count"],
            "retained_after_categorical_temperature": reports[
                "mechanism_temperature_robustness"
            ]["analysis"]["retained_association_count"],
            "haven_experimental_compatibility": reports["haven_validation"][
                "experimental_comparison"
            ]["compatible_with_new_configuration_prediction"],
            "experiment_points_inside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is True
                for row in reports["experimental_validation"]["comparisons"]
            ),
            "experiment_points_outside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is False
                for row in reports["experimental_validation"]["comparisons"]
            ),
            "negative_outcomes_change_claim_not_completeness": True,
        },
        "git_state_at_generation": git_state(_ROOT),
        "environment": environment_versions(
            ("numpy", "scipy", "matplotlib", "ase", "chgnet", "torch")
        ),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
        "base_publication_implementation": {
            "path": str(Path(base.__file__).resolve()),
            "sha256": sha256_file(base.__file__),
        },
    }
    manifest["manifest_gate_pass"] = all(manifest["checks"].values())
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    destination = _repo_path(protocol["output"]["artifact_manifest"])
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite publication manifest: {destination}")
    atomic_write_json(destination, manifest)
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    args = parser.parse_args()
    result = build_research_publication_package(args.protocol)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
