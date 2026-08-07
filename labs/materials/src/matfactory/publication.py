"""Generate the frozen LLZTO publication figures, tables, and artifact manifest."""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .evidence_audit import validate_exclusion_ledger
from .provenance import (
    atomic_write_json,
    atomic_write_text,
    canonical_json,
    environment_versions,
    fingerprint,
    git_state,
    sha256_file,
)


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(__file__).resolve().parents[2] / path).resolve()


def _verify_fingerprint(payload: dict[str, Any], field: str, *, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _load_fingerprinted(
    path: Path,
    *,
    fingerprint_field: str | None,
    label: str,
) -> dict[str, Any]:
    payload = _read_json(path)
    if fingerprint_field is not None:
        _verify_fingerprint(payload, fingerprint_field, label=label)
    return payload


def _discover_hash_pairs(value: Any) -> list[dict[str, str]]:
    """Find common path/SHA pairs embedded in report provenance recursively."""
    pairs: list[dict[str, str]] = []
    if isinstance(value, dict):
        direct_path = value.get("path")
        direct_sha = value.get("sha256")
        if isinstance(direct_path, str) and isinstance(direct_sha, str):
            pairs.append({"path": direct_path, "sha256": direct_sha})
        for key, path_value in value.items():
            if not key.endswith("_path") or not isinstance(path_value, str):
                continue
            sha_value = value.get(key[: -len("_path")] + "_sha256")
            if isinstance(sha_value, str):
                pairs.append({"path": path_value, "sha256": sha_value})
        for nested in value.values():
            pairs.extend(_discover_hash_pairs(nested))
    elif isinstance(value, list):
        for nested in value:
            pairs.extend(_discover_hash_pairs(nested))
    return pairs


def _verified_sources(
    root_reports: list[tuple[str, Path, dict[str, Any]]]
) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for source_id, path, payload in root_reports:
        resolved = path.resolve()
        records[str(resolved)] = {
            "source_id": source_id,
            "path": str(resolved),
            "sha256": sha256_file(resolved),
        }
        for pair in _discover_hash_pairs(payload):
            nested = Path(pair["path"])
            if not nested.is_absolute():
                nested = _repo_path(pair["path"])
            nested = nested.resolve()
            if not nested.is_file():
                raise FileNotFoundError(nested)
            actual = sha256_file(nested)
            if actual != pair["sha256"]:
                raise RuntimeError(f"publication source hash mismatch: {nested}")
            records.setdefault(
                str(nested),
                {
                    "source_id": "embedded-provenance",
                    "path": str(nested),
                    "sha256": actual,
                },
            )
    return [records[key] for key in sorted(records)]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_publication_inputs(protocol_path: Path | str) -> dict[str, Any]:
    """Load all complete reports and reject a partial or hash-inconsistent package."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("publication protocol schema_version must be '1.0'")
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
    }
    report_names = ["campaign_report", "evidence_audit_protocol", *fingerprint_fields]
    reports: dict[str, dict[str, Any]] = {}
    root_reports: list[tuple[str, Path, dict[str, Any]]] = []
    for name in report_names:
        path = _repo_path(paths[name])
        payload = _load_fingerprinted(
            path,
            fingerprint_field=fingerprint_fields.get(name),
            label=name,
        )
        reports[name] = payload
        root_reports.append((name, path, payload))

    _require(
        reports["campaign_report"].get("numerical_gate", {}).get(
            "all_energy_drift_checks_pass"
        )
        is True,
        "publication package requires the passed time-step gate",
    )
    for stage in ("cutoff", "kpoint", "scf"):
        decision = reports[f"{stage}_decision"]
        _require(
            decision.get("stage") == stage and decision.get("can_continue") is True,
            f"publication package requires a passing {stage} decision",
        )
    _require(
        reports["mpi_report"].get("mpi_equivalence_gate_pass") is True,
        "publication package requires MPI equivalence",
    )
    gate = reports["g2_release"]
    _require(
        gate.get("gate_id") == "g2-potential-domain"
        and gate.get("status") == "pass",
        "publication package requires the full G2 release",
    )
    _require(
        reports["hierarchical_transport"].get("hierarchical_gate_pass") is True,
        "publication package requires complete hierarchical transport",
    )
    _require(
        reports["nested_velocity"].get("result", {}).get(
            "nested_velocity_gate_pass"
        )
        is True,
        "publication package requires complete nested-velocity inference",
    )
    _require(
        reports["transport_sensitivity"].get("sensitivity_gate_pass") is True,
        "publication package requires passed size/volume sensitivity",
    )
    association = reports["mechanism_association"]
    _require(
        association.get("input_gate_pass") is True
        and association.get("analysis", {}).get("grid_gate_pass") is True
        and len(association.get("analysis_records", [])) == 25,
        "publication package requires the complete mechanism-association grid",
    )
    validation = reports["experimental_validation"]
    _require(
        validation.get("n_blocked") == 0
        and validation.get("n_evaluated") == validation.get("n_eligible_measurements")
        == 9,
        "publication package requires all nine experimental comparisons",
    )

    domain_reports: dict[str, dict[str, Any]] = {}
    for evidence in gate.get("evidence", []):
        kind = str(evidence.get("kind", ""))
        if not kind.startswith("domain:"):
            continue
        set_id = kind.split(":", 1)[1]
        path = Path(evidence["path"]).resolve()
        if sha256_file(path) != evidence["sha256"]:
            raise RuntimeError(f"G2 domain evidence hash mismatch: {path}")
        payload = _load_fingerprinted(
            path, fingerprint_field="report_fingerprint", label=kind
        )
        _require(
            payload.get("set_id") == set_id
            and payload.get("domain_gate_pass") is True,
            f"publication package requires passed domain set {set_id}",
        )
        domain_reports[set_id] = payload
        root_reports.append((kind, path, payload))
    _require(
        set(domain_reports) == {"feasibility", "publication-heldout"},
        "publication package requires both G2 domain reports",
    )

    ledger_path = _repo_path(paths["exclusion_ledger"])
    ledger = _read_json(ledger_path)
    ledger_validation = validate_exclusion_ledger(ledger, ledger_path=ledger_path)
    _require(
        ledger_validation["ledger_gate_pass"],
        "publication package exclusion ledger failed provenance validation",
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
        "reports": reports,
        "domain_reports": domain_reports,
        "transports": transports,
        "mechanisms": mechanisms,
        "source_manifest": _verified_sources(root_reports),
    }


def _csv_value(value: Any) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return value
    return canonical_json(value)


def write_table(
    table_id: str,
    title: str,
    rows: list[dict[str, Any]],
    directory: Path | str,
) -> dict[str, Any]:
    """Write one logical table as immutable canonical JSON and RFC-style CSV."""
    if not rows:
        raise ValueError(f"publication table {table_id} has no rows")
    output_dir = Path(directory).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{table_id}.json"
    csv_path = output_dir / f"{table_id}.csv"
    for path in (json_path, csv_path):
        if path.exists():
            raise RuntimeError(f"refusing to overwrite publication table: {path}")
    payload = {
        "schema_version": "1.0",
        "table_id": table_id,
        "title": title,
        "n_rows": len(rows),
        "rows": rows,
    }
    payload["table_fingerprint"] = fingerprint(payload)
    atomic_write_json(json_path, payload)
    columns = sorted({key for row in rows for key in row})
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=f".{csv_path.name}.",
        suffix=".tmp",
        dir=output_dir,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, csv_path)
    outputs = [
        {"format": path.suffix[1:], "path": str(path), "sha256": sha256_file(path)}
        for path in (json_path, csv_path)
    ]
    return {
        "table_id": table_id,
        "title": title,
        "n_rows": len(rows),
        "outputs": outputs,
    }


def _numeric_leaves(value: Any, prefix: str = "") -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    if isinstance(value, dict):
        for key, nested in sorted(value.items()):
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_numeric_leaves(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            path = f"{prefix}.{index}" if prefix else str(index)
            rows.extend(_numeric_leaves(nested, path))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number):
            rows.append((prefix, number))
    return rows


def _table_provenance(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in inputs["source_manifest"]]


def _table_dft(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    reports = inputs["reports"]
    rows = []
    for stage in ("cutoff", "kpoint", "scf"):
        decision = reports[f"{stage}_decision"]
        for comparison in decision["comparisons"]:
            row = {
                "row_type": "numerical_setting_comparison",
                "stage": stage,
                "comparison_index": comparison["index"],
                "passed": comparison["passed"],
                "selected_comparison": comparison["index"]
                == decision["selected_comparison_index"],
                "lower_settings": comparison["lower_settings"],
                "upper_settings": comparison["upper_settings"],
                "report_sha256": comparison["report_sha256"],
            }
            row.update(comparison.get("metrics", {}))
            rows.append(row)
    mpi = reports["mpi_report"]
    for comparison in mpi["comparisons"]:
        passed = bool(
            comparison["energy_abs_change_mev_atom"]
            <= mpi["limits"]["energy_abs_change_mev_atom_max"]
            and comparison["force_component_max_abs_change_ev_angstrom"]
            <= mpi["limits"]["force_component_max_abs_change_ev_angstrom"]
            and comparison["stress_component_max_abs_change_gpa"]
            <= mpi["limits"]["stress_component_max_abs_change_gpa"]
        )
        rows.append(
            {
                "row_type": "mpi_rank_comparison",
                "stage": "mpi",
                "passed": passed,
                **comparison,
            }
        )
    return rows


def _table_domain(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for set_id, report in sorted(inputs["domain_reports"].items()):
        groups: list[tuple[str, str, Any]] = [
            ("aggregate", "all", report["aggregate"]["metrics"]),
            *(
                ("temperature", key, value)
                for key, value in report["temperature_strata"].items()
            ),
            *(
                ("occupancy", key, value)
                for key, value in report["occupancy_strata"].items()
            ),
        ]
        element = report["aggregate"]["metrics"].get(
            "element_resolved_forces", {}
        )
        groups.extend(("element", key, value) for key, value in element.items())
        groups.extend(
            ("snapshot", str(value["snapshot_id"]), value)
            for value in report["snapshot_errors"]
        )
        for group_kind, group_id, values in groups:
            for metric, value in _numeric_leaves(values):
                rows.append(
                    {
                        "set_id": set_id,
                        "publication_claim_gate": report["publication_claim_gate"],
                        "domain_gate_pass": report["domain_gate_pass"],
                        "group_kind": group_kind,
                        "group_id": group_id,
                        "metric": metric,
                        "value": value,
                    }
                )
    return rows


def _table_transport(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for cell, payload in sorted(inputs["transports"].items()):
        run_id, temperature_label = cell.split("/T")
        estimate = payload["transport"]
        tracer = estimate["tracer"]
        collective = estimate["collective"]
        diagnostics = payload.get("trajectory_diagnostics", {})
        rows.append(
            {
                "run_id": run_id,
                "temperature_k": int(temperature_label),
                "tracer_diffusivity_cm2_s": tracer["diffusivity_cm2_s"],
                "tracer_stderr_cm2_s": tracer["diffusivity_stderr_cm2_s"],
                "tracer_r2": tracer["r2"],
                "tracer_diffusive_exponent": tracer["diffusive_exponent"],
                "tracer_fit_start_ps": tracer["fit_start_ps"],
                "tracer_fit_end_ps": tracer["fit_end_ps"],
                "tracer_final_msd_a2": estimate["final_tracer_msd_a2"],
                "tracer_resolved": payload["resolved_after_all_checks"],
                "tracer_rejection_reasons": payload.get(
                    "rejection_reasons_after_all_checks", []
                ),
                "collective_diffusivity_cm2_s": collective["diffusivity_cm2_s"],
                "collective_stderr_cm2_s": collective[
                    "diffusivity_stderr_cm2_s"
                ],
                "collective_r2": collective["r2"],
                "collective_diffusive_exponent": collective["diffusive_exponent"],
                "collective_fit_start_ps": collective["fit_start_ps"],
                "collective_fit_end_ps": collective["fit_end_ps"],
                "collective_final_msd_a2": estimate["final_collective_msd_a2"],
                "collective_resolved": payload[
                    "collective_resolved_after_all_checks"
                ],
                "collective_rejection_reasons": payload.get(
                    "collective_rejection_reasons_after_all_checks", []
                ),
                "collective_to_tracer_ratio": estimate[
                    "collective_to_tracer_ratio"
                ],
                "temperature_mean_k": diagnostics.get("temperature_mean_k"),
                "temperature_std_k": diagnostics.get("temperature_std_k"),
                "volume_mean_angstrom3": diagnostics.get("volume_mean_angstrom3"),
                "minimum_distance_angstrom": diagnostics.get(
                    "minimum_distance_angstrom"
                ),
                "protocol_fingerprint": payload.get("protocol_fingerprint"),
            }
        )
    return rows


def _table_hierarchical(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    report = inputs["reports"]["hierarchical_transport"]
    for estimator_name, estimator in report["estimators"].items():
        for fit in estimator["configuration_fits"]:
            rows.append(
                {
                    "row_type": "configuration_arrhenius_fit",
                    "estimator": estimator_name,
                    **fit,
                }
            )
        meta = estimator["activation_energy_random_effects"]
        rows.append(
            {
                "row_type": "activation_energy_population",
                "estimator": estimator_name,
                "activation_energy_ev": meta["mean"],
                "confidence_interval": meta["confidence_interval"],
                "prediction_interval": meta["prediction_interval"],
                "between_configuration_variance_tau2": meta[
                    "between_configuration_variance_tau2"
                ],
                "i2_fraction": meta["i2_fraction"],
                "method": meta["method"],
            }
        )
        predictions = estimator["nested_configuration_bootstrap"][
            "temperature_predictions"
        ]
        for temperature, prediction in predictions.items():
            rows.append(
                {
                    "row_type": "temperature_prediction",
                    "estimator": estimator_name,
                    "temperature_k": float(temperature),
                    "is_extrapolation": prediction["is_extrapolation"],
                    "population_geometric_mean": prediction[
                        "population_geometric_mean"
                    ],
                    "new_configuration_predictive": prediction[
                        "new_configuration_predictive"
                    ],
                }
            )
        curvature = estimator["non_arrhenius_diagnostic"]
        rows.append(
            {
                "row_type": "non_arrhenius_diagnostic",
                "estimator": estimator_name,
                **{
                    key: value
                    for key, value in curvature.items()
                    if key not in {"linear_parameters", "quadratic_parameters"}
                },
            }
        )
    return rows


def _table_sensitivity(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    velocity = inputs["reports"]["nested_velocity"]
    for record in velocity["records"]:
        for estimator, values in record["estimators"].items():
            rows.append(
                {
                    "row_type": "velocity_point",
                    "run_id": record["run_id"],
                    "occupancy_seed": record["occupancy_seed"],
                    "velocity_seed": record["velocity_seed"],
                    "estimator": estimator,
                    **values,
                }
            )
    for estimator, values in velocity["result"]["estimators"].items():
        for metric, value in _numeric_leaves(values):
            rows.append(
                {
                    "row_type": "nested_variance_inference",
                    "estimator": estimator,
                    "metric": metric,
                    "value": value,
                }
            )
    sensitivity = inputs["reports"]["transport_sensitivity"]
    for section in ("finite_size", "fixed_experimental_volume", "npt_volume"):
        for metric, value in _numeric_leaves(sensitivity[section]):
            rows.append(
                {
                    "row_type": "size_or_volume_sensitivity",
                    "section": section,
                    "metric": metric,
                    "value": value,
                }
            )
    return rows


def _table_mechanism_descriptors(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    association = inputs["reports"]["mechanism_association"]
    rows = []
    for record in association["analysis_records"]:
        cell = f"{record['group_id']}/T{record['temperature_k']}"
        mechanism = inputs["mechanisms"][cell]
        primary_string_window = mechanism["analysis_settings"]["string_windows_ps"]
        preferred = 0.4 if 0.4 in primary_string_window else primary_string_window[0]
        string = mechanism["strings"][format(preferred, ".12g")]
        responses = record["responses"]
        rows.append(
            {
                "run_id": record["group_id"],
                "occupancy_seed": record["occupancy_seed"],
                "temperature_k": record["temperature_k"],
                "volume_mean_angstrom3": record["volume_mean_angstrom3"],
                **record["primary_descriptors"],
                "tracer_diffusivity_cm2_s": math.exp(
                    responses["log_tracer_diffusivity"]["value"]
                ),
                "collective_diffusivity_cm2_s": math.exp(
                    responses["log_collective_diffusivity"]["value"]
                ),
                "collective_to_tracer_ratio": math.exp(
                    responses["log_collective_to_tracer_ratio"]["value"]
                ),
                "n_jumps": mechanism["n_jumps"],
                "mean_mobile_population_by_site_type": mechanism[
                    "mean_mobile_population_by_site_type"
                ],
                "dwell_summary_by_site_type": mechanism[
                    "dwell_summary_by_site_type"
                ],
                "transition_counts": mechanism["transition_counts"],
                "reverse_jumps": mechanism["reverse_jumps"],
                "primary_string_statistics": string,
                "mechanism_qualification": record["mechanism_qualification"],
            }
        )
    return rows


def _table_mechanism_associations(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = inputs["reports"]["mechanism_association"]["analysis"]
    rows = []
    for response, descriptors in analysis["associations"].items():
        for descriptor, result in descriptors.items():
            row = {
                "response": response,
                "descriptor": descriptor,
                "analysis_gate_pass": result["analysis_gate_pass"],
                "holm_adjusted_p_value": result["holm_adjusted_p_value"],
                "association_supported": result["association_supported"],
            }
            if result["analysis_gate_pass"]:
                row.update(
                    coefficient_per_sample_sd=result["primary_fit"][
                        "descriptor_coefficient_per_sample_sd"
                    ],
                    partial_weighted_r2=result["primary_fit"][
                        "partial_weighted_r2"
                    ],
                    permutation_p_value=result["permutation_test"][
                        "two_sided_p_value"
                    ],
                    cluster_bootstrap_quantiles=result["cluster_bootstrap"][
                        "quantiles"
                    ],
                    bootstrap_interval_excludes_zero=result[
                        "cluster_bootstrap"
                    ]["interval_excludes_zero"],
                    leave_one_occupancy_sign_stable=result[
                        "leave_one_occupancy_out"
                    ]["sign_stable"],
                    mechanism_setting_sign_stable=result[
                        "mechanism_setting_sensitivity"
                    ]["sign_stable"],
                    sensitivity_slope_range=result[
                        "mechanism_setting_sensitivity"
                    ]["slope_range"],
                )
            else:
                row["error"] = result.get("error")
            rows.append(row)
    return rows


def _table_experiment_exclusions(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    validation = inputs["reports"]["experimental_validation"]
    for comparison in validation["comparisons"]:
        rows.append({"row_type": "experimental_comparison", **comparison})
    ledger = inputs["reports"]["exclusion_ledger"]
    for entry in ledger["entries"]:
        rows.append(
            {
                "row_type": "exclusion_or_negative_result",
                **entry,
            }
        )
    return rows


_TABLE_BUILDERS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "table01-provenance": _table_provenance,
    "table02-dft-convergence": _table_dft,
    "table03-domain-errors": _table_domain,
    "table04-formal-transport-points": _table_transport,
    "table05-hierarchical-arrhenius": _table_hierarchical,
    "table06-replication-and-sensitivity": _table_sensitivity,
    "table07-mechanism-descriptors": _table_mechanism_descriptors,
    "table08-mechanism-associations": _table_mechanism_associations,
    "table09-experiment-and-exclusions": _table_experiment_exclusions,
}


def build_publication_tables(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    protocol = inputs["protocol"]
    output_dir = _repo_path(protocol["output"]["table_directory"])
    expected = [row["table_id"] for row in protocol["tables"]]
    if set(expected) != set(_TABLE_BUILDERS):
        raise ValueError("publication table protocol and implementation differ")
    return [
        write_table(
            specification["table_id"],
            specification["title"],
            _TABLE_BUILDERS[specification["table_id"]](inputs),
            output_dir,
        )
        for specification in protocol["tables"]
    ]


def save_figure(
    figure: Any,
    figure_id: str,
    title: str,
    directory: Path | str,
    *,
    formats: list[str],
    png_dpi: int,
) -> dict[str, Any]:
    """Atomically save one logical figure in every frozen output format."""
    output_dir = Path(directory).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for format_name in formats:
        if format_name not in {"svg", "pdf", "png"}:
            raise ValueError(f"unsupported publication figure format {format_name}")
        path = output_dir / f"{figure_id}.{format_name}"
        if path.exists():
            raise RuntimeError(f"refusing to overwrite publication figure: {path}")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{figure_id}.", suffix=f".{format_name}", dir=output_dir
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        metadata: dict[str, Any] = {"Creator": "matfactory"}
        if format_name == "pdf":
            metadata.update(CreationDate=None, ModDate=None)
        elif format_name == "svg":
            metadata.update(Date=None)
        try:
            figure.savefig(
                temporary,
                format=format_name,
                dpi=png_dpi if format_name == "png" else None,
                metadata=metadata,
                bbox_inches="tight",
            )
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        outputs.append(
            {
                "format": format_name,
                "path": str(path),
                "sha256": sha256_file(path),
            }
        )
    return {
        "figure_id": figure_id,
        "title": title,
        "outputs": outputs,
    }


def _configure_matplotlib(protocol: dict[str, Any]) -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style = protocol["style"]
    plt.rcParams.update(
        {
            "font.family": style["font_family"],
            "font.size": style["minimum_axis_font_pt"],
            "axes.titlesize": style["minimum_panel_label_font_pt"],
            "axes.labelsize": style["minimum_axis_font_pt"],
            "legend.fontsize": max(6, style["minimum_axis_font_pt"] - 1),
            "svg.hashsalt": "matfactory-llzto-publication-v1",
        }
    )
    return plt


def _plot_workflow(inputs: dict[str, Any], *, package_outputs_complete: bool) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    figure, axis = plt.subplots(figsize=(13.0, 3.2))
    axis.set_axis_off()
    labels = [
        ("G0", "provenance"),
        ("G1", "time step"),
        ("G2", "DFT domain"),
        ("G3", "formal MD"),
        ("G4", "replication"),
        ("G5", "experiment"),
        ("G6", "mechanisms"),
        ("G7", "evidence package"),
    ]
    statuses = [True] * 7 + [package_outputs_complete]
    accepted = inputs["protocol"]["style"]["equivalence_color"]
    blocked = inputs["protocol"]["style"]["negative_or_blocked_color"]
    for index, ((gate, label), passed) in enumerate(zip(labels, statuses)):
        x = index / (len(labels) - 1)
        color = accepted if passed else blocked
        axis.text(
            x,
            0.55,
            f"{gate}\n{label}\n{'PASS' if passed else 'BLOCK'}",
            ha="center",
            va="center",
            transform=axis.transAxes,
            color="white",
            bbox={"boxstyle": "round,pad=0.45", "facecolor": color, "edgecolor": "none"},
        )
        if index < len(labels) - 1:
            next_x = (index + 1) / (len(labels) - 1)
            axis.annotate(
                "",
                xy=(next_x - 0.045, 0.55),
                xytext=(x + 0.045, 0.55),
                xycoords=axis.transAxes,
                arrowprops={"arrowstyle": "->", "color": "#333333", "lw": 1.2},
            )
    axis.text(
        0.5,
        0.08,
        "Every box is backed by immutable report and source hashes; passing G7 permits only a final qualitative journal-level assessment.",
        ha="center",
        va="center",
        transform=axis.transAxes,
    )
    figure.suptitle("Auditable LLZTO evidence workflow")
    return figure


def _plot_dft_convergence(inputs: dict[str, Any]) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    reports = inputs["reports"]
    metrics = (
        (
            "max_pairwise_relative_energy_change_mev_atom",
            "Relative energy / limit",
        ),
        (
            "force_component_max_abs_change_ev_angstrom",
            "Max |force change| / limit",
        ),
        (
            "stress_component_max_abs_change_gpa",
            "Max |stress change| / limit",
        ),
    )
    records = []
    for stage in ("cutoff", "kpoint", "scf"):
        for comparison in reports[f"{stage}_decision"]["comparisons"]:
            payload = _read_json(comparison["report_path"])
            records.append(
                {
                    "label": f"{stage}-{comparison['index'] + 1}",
                    "metrics": payload["metrics"],
                    "limits": payload["limits"],
                    "pass": payload["numerically_converged"],
                }
            )
    mpi = reports["mpi_report"]
    records.append(
        {
            "label": "MPI 1/2/4/8",
            "metrics": {
                "max_pairwise_relative_energy_change_mev_atom": mpi["metrics"][
                    "energy_abs_change_mev_atom_max"
                ],
                "force_component_max_abs_change_ev_angstrom": mpi["metrics"][
                    "force_component_max_abs_change_ev_angstrom"
                ],
                "stress_component_max_abs_change_gpa": mpi["metrics"][
                    "stress_component_max_abs_change_gpa"
                ],
            },
            "limits": {
                "max_pairwise_relative_energy_change_mev_atom": mpi["limits"][
                    "energy_abs_change_mev_atom_max"
                ],
                "force_component_max_abs_change_ev_angstrom": mpi["limits"][
                    "force_component_max_abs_change_ev_angstrom"
                ],
                "stress_component_max_abs_change_gpa": mpi["limits"][
                    "stress_component_max_abs_change_gpa"
                ],
            },
            "pass": mpi["mpi_equivalence_gate_pass"],
        }
    )
    figure, axes = plt.subplots(1, 3, figsize=(13.5, 3.8), sharex=True)
    accepted = inputs["protocol"]["style"]["accepted_color"]
    rejected = inputs["protocol"]["style"]["negative_or_blocked_color"]
    x = np.arange(len(records))
    for axis, (metric, title) in zip(axes, metrics):
        values = [row["metrics"][metric] / row["limits"][metric] for row in records]
        colors = [accepted if row["pass"] else rejected for row in records]
        axis.bar(x, values, color=colors)
        axis.axhline(1.0, color="#D55E00", linestyle="--", linewidth=1.2)
        axis.set_yscale("log")
        axis.set_ylabel(title)
        axis.set_xticks(x, [row["label"] for row in records], rotation=35, ha="right")
        axis.grid(axis="y", alpha=0.2)
    figure.suptitle("Numerical changes normalized by preregistered acceptance limits")
    figure.tight_layout()
    return figure


def _domain_parity_values(report: dict[str, Any]) -> dict[str, np.ndarray]:
    dft_energy = []
    model_energy = []
    dft_force = []
    model_force = []
    dft_stress = []
    model_stress = []
    for source in report["sources"]:
        dft = _read_json(source["dft_label_path"])["result"]
        model = _read_json(source["model_label_path"])["result"]
        dft_forces = np.asarray(dft["forces_ev_angstrom"], dtype=float)
        model_forces = np.asarray(model["forces_ev_angstrom"], dtype=float)
        dft_energy.append(float(dft["total_energy_ev"]) / len(dft_forces))
        model_energy.append(float(model["total_energy_ev"]) / len(model_forces))
        dft_force.append(dft_forces.reshape(-1))
        model_force.append(model_forces.reshape(-1))
        dft_stress.append(np.asarray(dft["stress_gpa"], dtype=float).reshape(-1))
        model_stress.append(np.asarray(model["stress_gpa"], dtype=float).reshape(-1))
    dft_energy_array = np.asarray(dft_energy)
    model_energy_array = np.asarray(model_energy)
    return {
        "dft_energy": dft_energy_array - dft_energy_array.mean(),
        "model_energy": model_energy_array - model_energy_array.mean(),
        "dft_force": np.concatenate(dft_force),
        "model_force": np.concatenate(model_force),
        "dft_stress": np.concatenate(dft_stress),
        "model_stress": np.concatenate(model_stress),
    }


def _parity_limits(axis: Any, x: np.ndarray, y: np.ndarray) -> None:
    lower = float(min(np.min(x), np.min(y)))
    upper = float(max(np.max(x), np.max(y)))
    padding = max((upper - lower) * 0.05, 1e-12)
    axis.plot([lower - padding, upper + padding], [lower - padding, upper + padding], "k--", lw=1)
    axis.set_xlim(lower - padding, upper + padding)
    axis.set_ylim(lower - padding, upper + padding)


def _plot_domain(inputs: dict[str, Any]) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    figure, axes = plt.subplots(1, 3, figsize=(13.5, 4.1))
    colors = {"feasibility": "#999999", "publication-heldout": "#0072B2"}
    for set_id, report in sorted(inputs["domain_reports"].items()):
        values = _domain_parity_values(report)
        color = colors.get(set_id, "#333333")
        axes[0].scatter(
            values["dft_energy"] * 1000,
            values["model_energy"] * 1000,
            s=24,
            alpha=0.8,
            color=color,
            label=f"{set_id} (n={report['n_snapshots']})",
        )
        step = max(1, len(values["dft_force"]) // 5000)
        axes[1].scatter(
            values["dft_force"][::step],
            values["model_force"][::step],
            s=4,
            alpha=0.25,
            color=color,
            label=set_id,
        )
        axes[2].scatter(
            values["dft_stress"],
            values["model_stress"],
            s=10,
            alpha=0.5,
            color=color,
            label=set_id,
        )
    for axis, x_key, y_key in (
        (axes[0], "dft_energy", "model_energy"),
        (axes[1], "dft_force", "model_force"),
        (axes[2], "dft_stress", "model_stress"),
    ):
        all_values = [_domain_parity_values(report) for report in inputs["domain_reports"].values()]
        _parity_limits(
            axis,
            np.concatenate([value[x_key] for value in all_values])
            * (1000 if x_key == "dft_energy" else 1),
            np.concatenate([value[y_key] for value in all_values])
            * (1000 if y_key == "model_energy" else 1),
        )
        axis.grid(alpha=0.15)
    axes[0].set(xlabel="DFT centered energy (meV atom$^{-1}$)", ylabel="CHGNet centered energy (meV atom$^{-1}$)")
    axes[1].set(xlabel="DFT force component (eV Å$^{-1}$)", ylabel="CHGNet force component (eV Å$^{-1}$)")
    axes[2].set(xlabel="DFT stress component (GPa)", ylabel="CHGNet stress component (GPa)")
    axes[0].legend(frameon=False)
    figure.suptitle("CHGNet–DFT parity on development and publication-heldout domains")
    figure.tight_layout()
    return figure


def _ordered_formal_cells(inputs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    association = inputs["reports"]["mechanism_association"]
    records = sorted(
        association["analysis_records"],
        key=lambda row: (int(row["occupancy_seed"]), int(row["temperature_k"])),
    )
    return [
        (
            f"{row['group_id']}/T{row['temperature_k']}",
            row,
        )
        for row in records
    ]


def _plot_msd(inputs: dict[str, Any]) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    figure, axes = plt.subplots(5, 5, figsize=(15.5, 14.5), sharex=True, sharey=True)
    tracer_color = inputs["protocol"]["style"]["accepted_color"]
    collective_color = inputs["protocol"]["style"]["collective_color"]
    for axis, (cell, record) in zip(axes.flat, _ordered_formal_cells(inputs)):
        payload = inputs["transports"][cell]
        estimate = payload["transport"]
        curve = estimate["curve"]
        times = np.asarray(curve["times_ps"])
        axis.loglog(times, curve["tracer_msd_a2"], color=tracer_color, lw=1.0, label="tracer")
        axis.loglog(times, curve["collective_msd_a2"], color=collective_color, lw=1.0, label="collective")
        tracer = estimate["tracer"]
        collective = estimate["collective"]
        axis.axvspan(
            max(tracer["fit_start_ps"], collective["fit_start_ps"]),
            min(tracer["fit_end_ps"], collective["fit_end_ps"]),
            color="#999999",
            alpha=0.12,
        )
        axis.axhline(20.0, color="#666666", ls=":", lw=0.7)
        passed = bool(
            payload["resolved_after_all_checks"]
            and payload["collective_resolved_after_all_checks"]
        )
        axis.set_title(
            f"occ {record['occupancy_seed']}, {record['temperature_k']} K "
            f"{'✓' if passed else '×'}\n"
            f"αt={tracer['diffusive_exponent']:.2f}, αc={collective['diffusive_exponent']:.2f}"
        )
        axis.grid(alpha=0.12, which="both")
    for axis in axes[-1, :]:
        axis.set_xlabel("lag time (ps)")
    for axis in axes[:, 0]:
        axis.set_ylabel("MSD (Å$^2$)")
    axes[0, 0].legend(frameon=False, loc="lower right")
    figure.suptitle(
        "All formal tracer and collective MSD curves (shading = common fit window; dotted = 20 Å²)"
    )
    figure.tight_layout(rect=(0, 0, 1, 0.98))
    return figure


def _prediction_interval(prediction: dict[str, Any]) -> tuple[float, float, float]:
    quantiles = prediction["new_configuration_predictive"][
        "diffusivity_cm2_s_quantiles"
    ]
    ordered = sorted((float(key), float(value)) for key, value in quantiles.items())
    return ordered[0][1], ordered[len(ordered) // 2][1], ordered[-1][1]


def _plot_arrhenius(inputs: dict[str, Any]) -> Any:
    from .mlipmd import K_B_EV

    plt = _configure_matplotlib(inputs["protocol"])
    figure, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))
    association = inputs["reports"]["mechanism_association"]
    hierarchical = inputs["reports"]["hierarchical_transport"]
    response_names = (
        ("tracer", "log_tracer_diffusivity", "Tracer D (cm$^2$ s$^{-1}$)"),
        (
            "collective",
            "log_collective_diffusivity",
            "Collective D (cm$^2$ s$^{-1}$)",
        ),
    )
    groups = sorted({row["group_id"] for row in association["analysis_records"]})
    colors = plt.cm.viridis(np.linspace(0.08, 0.92, len(groups)))
    color_by_group = dict(zip(groups, colors))
    for axis, (estimator_name, response_name, ylabel) in zip(axes, response_names):
        estimator = hierarchical["estimators"][estimator_name]
        fits = {row["group_id"]: row for row in estimator["configuration_fits"]}
        for group in groups:
            records = sorted(
                [
                    row
                    for row in association["analysis_records"]
                    if row["group_id"] == group
                ],
                key=lambda row: row["temperature_k"],
            )
            temperatures = np.asarray([row["temperature_k"] for row in records])
            log_values = np.asarray(
                [row["responses"][response_name]["value"] for row in records]
            )
            values = np.exp(log_values)
            errors = values * np.sqrt(
                [row["responses"][response_name]["variance"] for row in records]
            )
            x = 1000.0 / temperatures
            color = color_by_group[group]
            axis.errorbar(
                x,
                values,
                yerr=errors,
                marker="o",
                color=color,
                capsize=2,
                linestyle="none",
                label=group.replace("formal-", ""),
            )
            fit = fits[group]
            grid_t = np.linspace(700, 900, 150)
            predicted = np.exp(
                fit["log_prefactor_cm2_s"]
                - fit["activation_energy_ev"] / (K_B_EV * grid_t)
            )
            axis.plot(1000.0 / grid_t, predicted, color=color, lw=1.0)
        axis.set_yscale("log")
        axis.set_xlabel("1000/T (K$^{-1}$)")
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.18)
        predictions = estimator["nested_configuration_bootstrap"][
            "temperature_predictions"
        ]
        room_key = min(predictions, key=lambda key: abs(float(key) - 300.0))
        lower, median, upper = _prediction_interval(predictions[room_key])
        inset = axis.inset_axes([0.60, 0.10, 0.34, 0.36])
        inset.errorbar(
            [0],
            [median],
            yerr=[[median - lower], [upper - median]],
            marker="D",
            color="#333333",
            capsize=3,
        )
        inset.set_yscale("log")
        inset.set_xticks([0], [f"{float(room_key):g} K"])
        inset.set_title("extrapolated\nnew configuration", fontsize=7)
        inset.grid(axis="y", alpha=0.15)
    axes[0].legend(frameon=False, fontsize=6, ncol=2)
    figure.suptitle("Configuration-resolved Arrhenius fits and explicit room-temperature extrapolation")
    figure.tight_layout()
    return figure


def _plot_velocity(inputs: dict[str, Any]) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    report = inputs["reports"]["nested_velocity"]
    figure, axes = plt.subplots(1, 3, figsize=(13.5, 4.3))
    estimators = (
        ("tracer", "Tracer D (cm$^2$ s$^{-1}$)"),
        ("collective", "Collective D (cm$^2$ s$^{-1}$)"),
        ("collective_to_tracer_ratio", "Collective / tracer"),
    )
    for axis, (estimator, ylabel) in zip(axes, estimators):
        by_occupancy: dict[int, list[float]] = {}
        for occupancy in sorted(
            {int(record["occupancy_seed"]) for record in report["records"]}
        ):
            selected = sorted(
                [
                    record
                    for record in report["records"]
                    if int(record["occupancy_seed"]) == occupancy
                ],
                key=lambda record: int(record["velocity_seed"]),
            )
            jitter = np.linspace(-0.16, 0.16, len(selected))
            for offset, record in zip(jitter, selected):
                value = float(record["estimators"][estimator]["value"])
                by_occupancy.setdefault(occupancy, []).append(value)
                axis.scatter(
                    occupancy + offset,
                    value,
                    color="#0072B2",
                    s=28,
                    alpha=0.8,
                )
        for occupancy, values in sorted(by_occupancy.items()):
            axis.plot(
                [occupancy - 0.22, occupancy + 0.22],
                [np.mean(values), np.mean(values)],
                color="#D55E00",
                lw=2,
            )
        inference = report["result"]["estimators"][estimator]
        occupancy_variance = inference.get("occupancy_variance_log_scale")
        velocity_variance = inference.get("velocity_variance_log_scale")
        if occupancy_variance is not None and velocity_variance is not None:
            axis.set_title(
                f"σocc={math.sqrt(occupancy_variance):.2g}; "
                f"σvel={math.sqrt(velocity_variance):.2g} (log scale)"
            )
        axis.set_xlabel("occupancy realization")
        axis.set_ylabel(ylabel)
        axis.set_xticks(sorted(by_occupancy))
        if estimator != "collective_to_tracer_ratio":
            axis.set_yscale("log")
        axis.grid(alpha=0.15)
    figure.suptitle("Balanced five-occupancy by three-velocity design at 800 K")
    figure.tight_layout()
    return figure


def _effect_interval(estimator: dict[str, Any]) -> tuple[float, float, float]:
    quantiles = estimator["bootstrap"]["ratio_quantiles"]
    ordered = sorted((float(key), float(value)) for key, value in quantiles.items())
    return ordered[0][1], float(estimator["central_ratio"]), ordered[-1][1]


def _plot_sensitivity(inputs: dict[str, Any]) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    report = inputs["reports"]["transport_sensitivity"]
    figure, axes = plt.subplots(1, 3, figsize=(14.5, 5.5), sharex=True)
    sections: list[tuple[str, list[dict[str, Any]]]] = [
        ("Finite size, 800 K", [report["finite_size"]]),
        ("Fixed experimental volume, 800 K", [report["fixed_experimental_volume"]]),
        ("NPT versus fixed volume", report["npt_volume"]["by_temperature"]),
    ]
    estimator_labels = {
        "tracer": "tracer",
        "collective": "collective",
        "collective_to_tracer_ratio": "ratio",
    }
    for axis, (title, comparisons) in zip(axes, sections):
        rows = []
        for comparison in comparisons:
            temperature = comparison.get("temperature_k", 800)
            for estimator, values in comparison["estimators"].items():
                lower, center, upper = _effect_interval(values)
                rows.append((f"{temperature} K {estimator_labels[estimator]}", lower, center, upper, values["equivalence_supported"]))
        y = np.arange(len(rows))
        for index, (label, lower, center, upper, passed) in enumerate(rows):
            color = "#009E73" if passed else "#666666"
            axis.errorbar(
                center,
                index,
                xerr=[[max(0.0, center - lower)], [max(0.0, upper - center)]],
                marker="o",
                color=color,
                capsize=2,
            )
        margin = float(comparisons[0]["estimators"][next(iter(comparisons[0]["estimators"]))]["equivalence_ratio_margin"])
        axis.axvspan(1.0 / margin, margin, color="#009E73", alpha=0.10)
        axis.axvline(1.0, color="black", lw=0.8)
        axis.set_xscale("log")
        axis.set_yticks(y, [row[0] for row in rows])
        axis.set_xlabel("comparison / reference")
        axis.set_title(title)
        axis.grid(axis="x", alpha=0.18)
    figure.suptitle("Block-bootstrap finite-size and volume effects with frozen equivalence regions")
    figure.tight_layout()
    return figure


def _plot_mechanisms(inputs: dict[str, Any]) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    association = inputs["reports"]["mechanism_association"]
    records = association["analysis_records"]
    descriptors = (
        "log_jump_rate",
        "tetrahedral_population_fraction",
        "reverse_pair_fraction",
        "string_excess",
    )
    labels = {
        "log_jump_rate": "log jump rate",
        "tetrahedral_population_fraction": "tetrahedral population fraction",
        "reverse_pair_fraction": "reverse-pair fraction",
        "string_excess": "null-corrected string excess",
    }
    figure = plt.figure(figsize=(14.5, 8.0))
    grid = figure.add_gridspec(2, 3, width_ratios=[1, 1, 1.35])
    scatter_axes = [figure.add_subplot(grid[row, column]) for row in range(2) for column in range(2)]
    forest_axis = figure.add_subplot(grid[:, 2])
    temperatures = np.asarray([row["temperature_k"] for row in records])
    colors = plt.cm.plasma((temperatures - temperatures.min()) / (temperatures.max() - temperatures.min()))
    ratio = np.exp(
        [row["responses"]["log_collective_to_tracer_ratio"]["value"] for row in records]
    )
    for axis, descriptor in zip(scatter_axes, descriptors):
        x = [row["primary_descriptors"][descriptor] for row in records]
        axis.scatter(x, ratio, c=colors, s=30, edgecolor="none")
        axis.set_xlabel(labels[descriptor])
        axis.set_ylabel("collective / tracer")
        axis.grid(alpha=0.15)
    combinations = []
    for response, values in association["analysis"]["associations"].items():
        for descriptor, result in values.items():
            if not result["analysis_gate_pass"]:
                continue
            quantiles = result["cluster_bootstrap"]["quantiles"]
            ordered = sorted((float(key), float(value)) for key, value in quantiles.items())
            combinations.append(
                (
                    f"{response.replace('log_', '').replace('_diffusivity', '')}\n{labels[descriptor]}",
                    float(result["primary_fit"]["descriptor_coefficient_per_sample_sd"]),
                    ordered[0][1],
                    ordered[-1][1],
                    result["association_supported"],
                )
            )
    y = np.arange(len(combinations))
    for index, (label, center, lower, upper, supported) in enumerate(combinations):
        forest_axis.errorbar(
            center,
            index,
            xerr=[[max(0.0, center - lower)], [max(0.0, upper - center)]],
            marker="o",
            color="#009E73" if supported else "#666666",
            capsize=2,
        )
    forest_axis.axvline(0.0, color="black", lw=0.8)
    forest_axis.set_yticks(y, [row[0] for row in combinations], fontsize=6)
    forest_axis.set_xlabel("change in log response per descriptor SD")
    forest_axis.set_title("Cluster-bootstrap association intervals\n(Holm + LOCO + sensitivity required)")
    forest_axis.grid(axis="x", alpha=0.15)
    figure.suptitle(
        "Mechanism descriptors, Haven-type relation, and non-causal association diagnostics"
    )
    figure.tight_layout()
    return figure


def _plot_experiment(inputs: dict[str, Any]) -> Any:
    plt = _configure_matplotlib(inputs["protocol"])
    comparisons = inputs["reports"]["experimental_validation"]["comparisons"]
    evaluated = [row for row in comparisons if row["status"] == "evaluated"]
    figure, axis = plt.subplots(figsize=(10.5, max(4.5, 0.55 * len(evaluated))))
    labels = []
    for index, row in enumerate(evaluated):
        observed = float(row["observed"])
        interval = row["new_configuration_prediction_interval"]
        center = float(row["predicted_population_median"]) / observed
        lower = float(interval["lower"]) / observed
        upper = float(interval["upper"]) / observed
        direct = row["benchmark_role"] == "primary_direct_measurement"
        compatible = row["compatible_with_simulation_prediction"]
        color = "#0072B2" if compatible else "#D55E00"
        marker = "o" if direct else "s"
        axis.errorbar(
            center,
            index,
            xerr=[[max(0.0, center - lower)], [max(0.0, upper - center)]],
            marker=marker,
            markerfacecolor=color if direct else "none",
            markeredgecolor=color,
            color=color,
            capsize=2,
        )
        temperature = row.get("temperature_k")
        labels.append(
            f"{row['record_id']} | {row['property']}"
            + (f" | {temperature:g} K" if isinstance(temperature, (int, float)) else "")
            + (" | derived" if not direct else "")
        )
    axis.axvline(1.0, color="black", lw=1.0, label="experiment")
    axis.set_xscale("log")
    axis.set_yticks(np.arange(len(evaluated)), labels)
    axis.set_xlabel("simulation population median / experimental value\n(error bar = new-configuration prediction interval)")
    axis.grid(axis="x", alpha=0.18)
    axis.set_title("Exact-composition like-for-like experimental comparison")
    figure.tight_layout()
    return figure


_FIGURE_BUILDERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "fig02-dft-numerical-convergence": _plot_dft_convergence,
    "fig03-chgnet-dft-domain": _plot_domain,
    "fig04-all-msd-diagnostics": _plot_msd,
    "fig05-hierarchical-arrhenius": _plot_arrhenius,
    "fig06-nested-velocity": _plot_velocity,
    "fig07-size-and-volume-sensitivity": _plot_sensitivity,
    "fig08-mechanisms-and-haven-relation": _plot_mechanisms,
    "fig09-experiment-comparison": _plot_experiment,
}


def _preflight_outputs(protocol: dict[str, Any]) -> None:
    output = protocol["output"]
    figure_dir = _repo_path(output["figure_directory"])
    table_dir = _repo_path(output["table_directory"])
    targets = [_repo_path(output["artifact_manifest"])]
    targets.extend(
        figure_dir / f"{specification['figure_id']}.{format_name}"
        for specification in protocol["figures"]
        for format_name in output["figure_formats"]
    )
    targets.extend(
        table_dir / f"{specification['table_id']}.{format_name}"
        for specification in protocol["tables"]
        for format_name in output["table_formats"]
    )
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise RuntimeError(
            "refusing to overwrite existing publication artifacts: "
            + ", ".join(existing)
        )


def _verify_output_entries(entries: list[dict[str, Any]], formats: list[str]) -> bool:
    expected = sorted(formats)
    for entry in entries:
        outputs = entry.get("outputs", [])
        if sorted(row.get("format") for row in outputs) != expected:
            return False
        for row in outputs:
            path = Path(row["path"]).resolve()
            if not path.is_file() or sha256_file(path) != row["sha256"]:
                return False
    return True


def build_publication_figures(
    inputs: dict[str, Any], *, package_tables_complete: bool
) -> list[dict[str, Any]]:
    protocol = inputs["protocol"]
    output = protocol["output"]
    figure_dir = _repo_path(output["figure_directory"])
    formats = list(output["figure_formats"])
    dpi = int(output["png_dpi"])
    specifications = {row["figure_id"]: row for row in protocol["figures"]}
    expected_non_workflow = set(specifications) - {"fig01-workflow-and-gates"}
    if expected_non_workflow != set(_FIGURE_BUILDERS):
        raise ValueError("publication figure protocol and implementation differ")
    generated: dict[str, dict[str, Any]] = {}
    plt = _configure_matplotlib(protocol)
    for figure_id in [
        row["figure_id"]
        for row in protocol["figures"]
        if row["figure_id"] != "fig01-workflow-and-gates"
    ]:
        figure = _FIGURE_BUILDERS[figure_id](inputs)
        try:
            generated[figure_id] = save_figure(
                figure,
                figure_id,
                specifications[figure_id]["title"],
                figure_dir,
                formats=formats,
                png_dpi=dpi,
            )
        finally:
            plt.close(figure)
    workflow = _plot_workflow(
        inputs,
        package_outputs_complete=bool(
            package_tables_complete
            and len(generated) == len(expected_non_workflow)
            and _verify_output_entries(list(generated.values()), formats)
        ),
    )
    try:
        generated["fig01-workflow-and-gates"] = save_figure(
            workflow,
            "fig01-workflow-and-gates",
            specifications["fig01-workflow-and-gates"]["title"],
            figure_dir,
            formats=formats,
            png_dpi=dpi,
        )
    finally:
        plt.close(workflow)
    return [generated[row["figure_id"]] for row in protocol["figures"]]


def build_publication_package(protocol_path: Path | str) -> dict[str, Any]:
    """Generate every frozen figure/table and write the immutable manifest last."""
    inputs = load_publication_inputs(protocol_path)
    protocol = inputs["protocol"]
    _preflight_outputs(protocol)
    tables = build_publication_tables(inputs)
    table_formats = list(protocol["output"]["table_formats"])
    tables_complete = bool(
        len(tables) == len(protocol["tables"])
        and _verify_output_entries(tables, table_formats)
    )
    figures = build_publication_figures(
        inputs, package_tables_complete=tables_complete
    )
    figure_formats = list(protocol["output"]["figure_formats"])
    figures_complete = bool(
        len(figures) == len(protocol["figures"])
        and _verify_output_entries(figures, figure_formats)
    )
    source_manifest = inputs["source_manifest"]
    sources_complete = all(
        Path(row["path"]).is_file()
        and sha256_file(row["path"]) == row["sha256"]
        for row in source_manifest
    )
    root = Path(__file__).resolve().parents[2]
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "llzto-publication-artifacts",
        "publication_protocol_path": str(inputs["protocol_path"]),
        "publication_protocol_sha256": sha256_file(inputs["protocol_path"]),
        "generation_command": (
            "uv run python -m matfactory.publication --protocol "
            "analysis/protocols/llzto_publication_package_v1.json"
        ),
        "sources": source_manifest,
        "figures": figures,
        "tables": tables,
        "checks": {
            "source_hashes_verified": sources_complete,
            "all_declared_figures_generated": figures_complete,
            "all_declared_tables_generated": tables_complete,
            "figure_count": len(figures) == len(protocol["figures"]),
            "table_count": len(tables) == len(protocol["tables"]),
            "negative_and_excluded_rows_retained": len(
                inputs["reports"]["exclusion_ledger"]["entries"]
            )
            >= 10,
        },
        "scientific_outcome_flags": {
            "supported_mechanism_association_count": inputs["reports"][
                "mechanism_association"
            ]["analysis"]["association_support_count"],
            "all_formal_strings_robustly_cooperative": inputs["reports"][
                "mechanism_association"
            ]["string_claim_qualification"][
                "all_25_trajectories_support_cooperative_strings_across_grid"
            ],
            "experiment_points_inside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is True
                for row in inputs["reports"]["experimental_validation"][
                    "comparisons"
                ]
            ),
            "experiment_points_outside_prediction_interval": sum(
                row.get("compatible_with_simulation_prediction") is False
                for row in inputs["reports"]["experimental_validation"][
                    "comparisons"
                ]
            ),
            "interpretation": (
                "These outcome flags change the scientific story but do not alter "
                "whether the complete preregistered analysis was retained."
            ),
        },
        "git_state_at_generation": git_state(root),
        "environment": environment_versions(
            ("numpy", "scipy", "matplotlib", "ase", "chgnet", "torch")
        ),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
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
    manifest = build_publication_package(args.protocol)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
