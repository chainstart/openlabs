"""Auditable CHGNet-versus-DFT applicability-domain validation for LLZTO."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from .dft import (
    STRESS_CONVENTION,
    atoms_fingerprint,
    compare_predictions,
)
from .dft_convergence import load_completed_qe_run
from .mlipmd import _model_metadata
from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    sha256_file,
)


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def load_domain_protocol(path: Path | str) -> tuple[dict[str, Any], Path]:
    """Load the frozen model-domain protocol and verify its DFT parent."""
    source = Path(path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("domain protocol schema_version must be '1.0'")
    required = {
        "protocol_id",
        "model",
        "aggregate_limits",
        "robustness_limits",
        "sets",
        "release_requirements",
    }
    if not required.issubset(protocol):
        raise ValueError("domain protocol is incomplete")
    project_root = Path(__file__).resolve().parents[2]
    dft_protocol = Path(protocol["reference_dft_protocol"])
    if not dft_protocol.is_absolute():
        dft_protocol = project_root / dft_protocol
    if sha256_file(dft_protocol) != protocol.get("reference_dft_protocol_sha256"):
        raise RuntimeError(f"reference DFT protocol hash mismatch: {dft_protocol}")
    if protocol["model"].get("stress_convention") != STRESS_CONVENTION:
        raise ValueError("model and DFT stress conventions are not aligned")
    return protocol, source


def _load_snapshot_set(
    path: Path | str,
    *,
    set_config: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    source = Path(path).resolve()
    manifest = _read_json(source)
    if manifest.get("schema_version") != "1.0":
        raise ValueError("snapshot manifest schema_version must be '1.0'")
    if manifest.get("selection_id") != set_config["selection_id"]:
        raise ValueError(
            f"snapshot selection is {manifest.get('selection_id')}, expected "
            f"{set_config['selection_id']}"
        )
    if int(manifest.get("n_snapshots", -1)) != int(set_config["expected_snapshots"]):
        raise ValueError("snapshot count does not match the frozen domain set")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != manifest["n_snapshots"]:
        raise ValueError("snapshot manifest has inconsistent rows")
    return manifest, source


def _verify_prediction_label(
    label: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    protocol_sha256: str,
    expected_model_sha256: str,
    expected_package_version: str | None = None,
) -> None:
    checks = {
        "snapshot_id": label.get("snapshot_id") == snapshot["snapshot_id"],
        "snapshot_sha256": label.get("snapshot_sha256")
        == snapshot["snapshot_sha256"],
        "structure_fingerprint": label.get("structure_fingerprint")
        == snapshot["structure_fingerprint"],
        "analysis_protocol_sha256": label.get("analysis_protocol_sha256")
        == protocol_sha256,
        "model_state_dict_sha256": label.get("model", {}).get(
            "state_dict_sha256"
        )
        == expected_model_sha256,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"model prediction provenance failed for {snapshot['snapshot_id']}: "
            + ", ".join(failed)
        )
    if expected_package_version is not None and label.get("environment", {}).get(
        "packages", {}
    ).get("chgnet") != expected_package_version:
        raise RuntimeError("model prediction uses an unexpected CHGNet package version")
    result = label.get("result", {})
    n_atoms = int(snapshot["n_atoms"])
    if np.asarray(result.get("forces_ev_angstrom"), dtype=float).shape != (n_atoms, 3):
        raise ValueError("model force label has the wrong shape")
    if np.asarray(result.get("stress_gpa"), dtype=float).shape != (3, 3):
        raise ValueError("model stress label has the wrong shape")
    if result.get("stress_convention") != STRESS_CONVENTION:
        raise ValueError("model prediction uses an incompatible stress convention")


def predict_snapshot_set(
    snapshot_manifest_path: Path | str,
    analysis_protocol_path: Path | str,
    *,
    set_id: str,
    out_dir: Path | str,
    device: str = "cpu",
) -> dict[str, Any]:
    """Create immutable CHGNet labels for a frozen snapshot set."""
    from ase.io import read
    from chgnet.model import CHGNet
    from pymatgen.io.ase import AseAtomsAdaptor

    protocol, protocol_path = load_domain_protocol(analysis_protocol_path)
    if set_id not in protocol["sets"]:
        raise ValueError(f"unknown domain set {set_id!r}")
    set_config = protocol["sets"][set_id]
    snapshots, snapshots_path = _load_snapshot_set(
        snapshot_manifest_path, set_config=set_config
    )
    if device not in {"cpu", "cuda", "mps"}:
        raise ValueError("device must be cpu, cuda, or mps")

    model = CHGNet.load(verbose=False, use_device=device)
    model_metadata = _model_metadata(model, protocol["model"]["name"])
    expected_model_sha256 = protocol["model"]["expected_state_dict_sha256"]
    if model_metadata["state_dict_sha256"] != expected_model_sha256:
        raise RuntimeError(
            "loaded CHGNet weights do not match the frozen domain protocol"
        )
    if bool(model.is_intensive) != bool(protocol["model"]["energy_is_intensive"]):
        raise RuntimeError("CHGNet energy extensivity differs from the protocol")
    environment = environment_versions(
        ("matfactory", "chgnet", "torch", "ase", "pymatgen", "numpy")
    )
    if environment["packages"]["chgnet"] != protocol["model"]["package_version"]:
        raise RuntimeError("installed CHGNet package version differs from the protocol")

    destination = Path(out_dir).resolve()
    labels_dir = destination / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    protocol_sha256 = sha256_file(protocol_path)
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots["snapshots"]:
        snapshot_path = Path(snapshot["snapshot_path"])
        if sha256_file(snapshot_path) != snapshot["snapshot_sha256"]:
            raise RuntimeError(f"snapshot hash mismatch: {snapshot_path}")
        atoms = read(snapshot_path, index=0)
        if atoms_fingerprint(atoms) != snapshot["structure_fingerprint"]:
            raise RuntimeError(
                f"snapshot structure mismatch: {snapshot['snapshot_id']}"
            )
        label_path = labels_dir / f"{snapshot['snapshot_id']}.json"
        if label_path.exists():
            label = _read_json(label_path)
            _verify_prediction_label(
                label,
                snapshot=snapshot,
                protocol_sha256=protocol_sha256,
                expected_model_sha256=expected_model_sha256,
                expected_package_version=protocol["model"]["package_version"],
            )
        else:
            structure = AseAtomsAdaptor.get_structure(atoms)
            prediction = model.predict_structure(structure, task="efs")
            energy = float(np.asarray(prediction["e"]).reshape(()))
            total_energy = energy * len(atoms) if model.is_intensive else energy
            forces = np.asarray(prediction["f"], dtype=float)
            stress = np.asarray(prediction["s"], dtype=float)
            if forces.shape != (len(atoms), 3) or stress.shape != (3, 3):
                raise RuntimeError("CHGNet returned an unexpected prediction shape")
            label = {
                "schema_version": "1.0",
                "label_kind": "chgnet-single-point",
                "set_id": set_id,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_path": str(snapshot_path.resolve()),
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "structure_fingerprint": snapshot["structure_fingerprint"],
                "n_atoms": len(atoms),
                "symbols": atoms.get_chemical_symbols(),
                "analysis_protocol_path": str(protocol_path),
                "analysis_protocol_sha256": protocol_sha256,
                "prediction_implementation_path": str(Path(__file__).resolve()),
                "prediction_implementation_sha256": sha256_file(Path(__file__)),
                "model": {
                    **model_metadata,
                    "package_version_required": protocol["model"]["package_version"],
                    "energy_is_intensive": bool(model.is_intensive),
                    "device": device,
                },
                "environment": environment,
                "result": {
                    "total_energy_ev": total_energy,
                    "forces_ev_angstrom": forces.tolist(),
                    "stress_gpa": stress.tolist(),
                    "stress_convention": STRESS_CONVENTION,
                },
            }
            atomic_write_json(label_path, label)
        rows.append(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "label_path": str(label_path),
                "label_sha256": sha256_file(label_path),
            }
        )

    manifest = {
        "schema_version": "1.0",
        "set_id": set_id,
        "snapshot_manifest_path": str(snapshots_path),
        "snapshot_manifest_sha256": sha256_file(snapshots_path),
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": protocol_sha256,
        "model_state_dict_sha256": expected_model_sha256,
        "n_predictions": len(rows),
        "predictions": rows,
    }
    manifest["prediction_set_fingerprint"] = fingerprint(manifest)
    manifest_path = destination / "prediction_manifest.json"
    if manifest_path.exists() and _read_json(manifest_path) != manifest:
        raise RuntimeError(f"prediction manifest changed: {manifest_path}")
    atomic_write_json(manifest_path, manifest)
    return manifest


def _group_error_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    force_errors = []
    stress_errors = []
    energy_errors = []
    for item in items:
        dft = item["dft"]
        model = item["model"]
        force_errors.append(
            np.asarray(model["forces_ev_angstrom"], dtype=float)
            - np.asarray(dft["forces_ev_angstrom"], dtype=float)
        )
        stress_errors.append(
            np.asarray(model["stress_gpa"], dtype=float)
            - np.asarray(dft["stress_gpa"], dtype=float)
        )
        energy_errors.append(
            (float(model["total_energy_ev"]) - float(dft["total_energy_ev"]))
            / int(item["n_atoms"])
        )
    force = np.concatenate([value.reshape(-1) for value in force_errors])
    stress = np.concatenate([value.reshape(-1) for value in stress_errors])
    energy = np.asarray(energy_errors, dtype=float)
    centered = energy - energy.mean()
    return {
        "n_snapshots": len(items),
        "force_component_mae_ev_angstrom": float(np.mean(np.abs(force))),
        "force_component_rmse_ev_angstrom": float(np.sqrt(np.mean(force**2))),
        "force_component_max_abs_ev_angstrom": float(np.max(np.abs(force))),
        "stress_component_mae_gpa": float(np.mean(np.abs(stress))),
        "stress_component_max_abs_mean_bias_gpa": float(
            np.max(np.abs(np.mean(np.stack(stress_errors), axis=0)))
        ),
        "centered_energy_mae_ev_atom": float(np.mean(np.abs(centered))),
    }


def build_domain_report(
    records: list[dict[str, Any]],
    protocol: dict[str, Any],
    *,
    set_id: str,
) -> dict[str, Any]:
    """Apply aggregate and preregistered stratified hard gates."""
    if set_id not in protocol["sets"]:
        raise ValueError(f"unknown domain set {set_id!r}")
    set_config = protocol["sets"][set_id]
    aggregate = compare_predictions(
        records,
        limits={
            name: float(value)
            for name, value in protocol["aggregate_limits"].items()
        },
    )
    robustness = protocol["robustness_limits"]
    by_temperature: dict[str, list[dict[str, Any]]] = {}
    by_occupancy: dict[str, list[dict[str, Any]]] = {}
    snapshot_metrics = []
    for item in records:
        temperature = item.get("temperature_k")
        if temperature is not None:
            by_temperature.setdefault(str(int(temperature)), []).append(item)
        occupancy = item.get("occupancy_seed")
        if occupancy is None:
            raise ValueError(f"record has no occupancy seed: {item.get('snapshot_id')}")
        by_occupancy.setdefault(str(int(occupancy)), []).append(item)
        metric = _group_error_metrics([item])
        snapshot_metrics.append(
            {
                "snapshot_id": item["snapshot_id"],
                "temperature_k": temperature,
                "occupancy_seed": int(occupancy),
                **metric,
            }
        )
    temperature_metrics = {
        key: _group_error_metrics(value) for key, value in sorted(by_temperature.items())
    }
    occupancy_metrics = {
        key: _group_error_metrics(value) for key, value in sorted(by_occupancy.items())
    }
    element_metrics = aggregate["metrics"]["element_resolved_forces"]
    li_metrics = element_metrics.get("Li")
    actual_temperatures = sorted(int(value) for value in by_temperature)
    actual_occupancies = sorted(int(value) for value in by_occupancy)
    required_temperatures = sorted(
        int(value) for value in set_config["required_temperature_strata_k"]
    )
    required_occupancies = sorted(
        int(value) for value in set_config["required_occupancy_seeds"]
    )
    rank = float(aggregate["metrics"]["relative_energy_spearman"])
    checks = {
        "expected_snapshot_count": len(records) == int(set_config["expected_snapshots"]),
        "required_temperature_strata": actual_temperatures == required_temperatures,
        "required_occupancy_strata": actual_occupancies == required_occupancies,
        "aggregate_limits": bool(aggregate["numerical_gate_pass"]),
        "relative_energy_rank": math.isfinite(rank)
        and rank >= float(robustness["relative_energy_spearman_min"]),
        "force_p95": aggregate["metrics"][
            "force_component_p95_abs_ev_angstrom"
        ]
        <= float(robustness["force_component_p95_abs_ev_angstrom_max"]),
        "li_force_mae": li_metrics is not None
        and li_metrics["component_mae_ev_angstrom"]
        <= float(robustness["li_force_component_mae_ev_angstrom_max"]),
        "all_element_force_mae": bool(element_metrics)
        and max(value["component_mae_ev_angstrom"] for value in element_metrics.values())
        <= float(robustness["any_element_force_component_mae_ev_angstrom_max"]),
        "all_temperature_force_mae": bool(temperature_metrics)
        and max(
            value["force_component_mae_ev_angstrom"]
            for value in temperature_metrics.values()
        )
        <= float(robustness["any_temperature_force_component_mae_ev_angstrom_max"]),
        "all_occupancy_force_mae": bool(occupancy_metrics)
        and max(
            value["force_component_mae_ev_angstrom"]
            for value in occupancy_metrics.values()
        )
        <= float(robustness["any_occupancy_force_component_mae_ev_angstrom_max"]),
        "all_snapshot_force_outliers": bool(snapshot_metrics)
        and max(
            value["force_component_max_abs_ev_angstrom"]
            for value in snapshot_metrics
        )
        <= float(
            robustness["any_snapshot_force_component_max_abs_ev_angstrom_max"]
        ),
        "stress_mean_bias": _group_error_metrics(records)[
            "stress_component_max_abs_mean_bias_gpa"
        ]
        <= float(robustness["stress_component_max_abs_mean_bias_gpa_max"]),
    }
    return {
        "schema_version": "1.0",
        "report_kind": "chgnet-dft-domain",
        "set_id": set_id,
        "publication_claim_gate": bool(set_config["publication_claim_gate"]),
        "n_snapshots": len(records),
        "aggregate": aggregate,
        "temperature_strata": temperature_metrics,
        "occupancy_strata": occupancy_metrics,
        "snapshot_errors": snapshot_metrics,
        "robustness_limits": robustness,
        "checks": checks,
        "domain_gate_pass": all(checks.values()),
        "failure_action": protocol["release_requirements"]["failure_action"],
    }


def _load_prediction_for_snapshot(
    prediction_dir: Path,
    snapshot: dict[str, Any],
    *,
    protocol_sha256: str,
    expected_model_sha256: str,
    expected_package_version: str,
) -> tuple[dict[str, Any], Path]:
    path = prediction_dir / "labels" / f"{snapshot['snapshot_id']}.json"
    label = _read_json(path)
    _verify_prediction_label(
        label,
        snapshot=snapshot,
        protocol_sha256=protocol_sha256,
        expected_model_sha256=expected_model_sha256,
        expected_package_version=expected_package_version,
    )
    return label, path


_NUMERICAL_SETTING_FIELDS = (
    "ecutwfc_ry",
    "ecutrho_ry",
    "kpoints",
    "conv_thr_ry",
    "electron_maxstep",
    "mixing_mode",
    "mixing_beta",
    "diagonalization",
)


def _selected_settings_from_final_scf(report: dict[str, Any]) -> dict[str, Any]:
    """Use the cheaper side of the passing final SCF adjacent comparison."""
    records = report.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("SCF convergence report has no matched records")
    settings = records[0].get("lower", {}).get("settings")
    if not isinstance(settings, dict):
        raise ValueError("SCF convergence report has no lower settings")
    selected = {field: settings.get(field) for field in _NUMERICAL_SETTING_FIELDS}
    if any(value is None for value in selected.values()):
        raise ValueError("SCF lower settings are incomplete")
    for record in records[1:]:
        other = record.get("lower", {}).get("settings", {})
        if any(other.get(field) != value for field, value in selected.items()):
            raise ValueError("SCF convergence structures use inconsistent settings")
    return selected


def build_domain_report_from_files(
    snapshot_manifest_path: Path | str,
    dft_campaign_dir: Path | str,
    prediction_dir: Path | str,
    analysis_protocol_path: Path | str,
    *,
    set_id: str,
    numerical_reports: dict[str, Path | str],
    out_path: Path | str,
) -> dict[str, Any]:
    """Join hash-verified DFT/model labels and write the domain report."""
    from ase.io import read

    protocol, protocol_path = load_domain_protocol(analysis_protocol_path)
    if set_id not in protocol["sets"]:
        raise ValueError(f"unknown domain set {set_id!r}")
    set_config = protocol["sets"][set_id]
    snapshots, snapshots_path = _load_snapshot_set(
        snapshot_manifest_path, set_config=set_config
    )
    required_stages = set(protocol["release_requirements"]["required_numerical_stages"])
    if set(numerical_reports) != required_stages:
        raise ValueError("domain report requires every frozen numerical stage")
    numerical_evidence = {}
    numerical_payloads = {}
    for stage, path_value in numerical_reports.items():
        path = Path(path_value).resolve()
        report = _read_json(path)
        if report.get("numerically_converged") is not True:
            raise RuntimeError(f"numerical stage {stage} has not converged: {path}")
        numerical_payloads[stage] = report
        numerical_evidence[stage] = {"path": str(path), "sha256": sha256_file(path)}
    selected_settings = _selected_settings_from_final_scf(numerical_payloads["scf"])

    campaign_dir = Path(dft_campaign_dir).resolve()
    campaign_path = campaign_dir / "dft_campaign_manifest.json"
    campaign = _read_json(campaign_path)
    if sha256_file(snapshots_path) != campaign.get("snapshot_manifest_sha256"):
        raise RuntimeError("DFT campaign does not belong to the snapshot manifest")
    runs_by_snapshot: dict[str, list[dict[str, Any]]] = {}
    for run in campaign.get("runs", []):
        runs_by_snapshot.setdefault(run["snapshot_id"], []).append(run)
    prediction_root = Path(prediction_dir).resolve()
    protocol_sha256 = sha256_file(protocol_path)
    expected_model_sha256 = protocol["model"]["expected_state_dict_sha256"]
    records: list[dict[str, Any]] = []
    sources = []
    for snapshot in snapshots["snapshots"]:
        candidates = runs_by_snapshot.get(snapshot["snapshot_id"], [])
        if len(candidates) != 1:
            raise ValueError(
                f"expected one final DFT run for {snapshot['snapshot_id']}, "
                f"found {len(candidates)}"
            )
        run = candidates[0]
        if any(
            run.get("settings", {}).get(field) != value
            for field, value in selected_settings.items()
        ):
            raise RuntimeError(
                f"DFT domain run does not use the selected converged settings: "
                f"{run['run_id']}"
            )
        completed = load_completed_qe_run(campaign_dir / run["run_id"])
        if completed["structure_fingerprint"] != snapshot["structure_fingerprint"]:
            raise RuntimeError("DFT and snapshot structures differ")
        model_label, model_path = _load_prediction_for_snapshot(
            prediction_root,
            snapshot,
            protocol_sha256=protocol_sha256,
            expected_model_sha256=expected_model_sha256,
            expected_package_version=protocol["model"]["package_version"],
        )
        snapshot_path = Path(snapshot["snapshot_path"])
        if sha256_file(snapshot_path) != snapshot["snapshot_sha256"]:
            raise RuntimeError(f"snapshot changed: {snapshot_path}")
        atoms = read(snapshot_path, index=0)
        metadata = snapshot.get("metadata") or {}
        occupancy = metadata.get("occupancy_seed")
        if occupancy is None:
            occupancy = set_config.get("default_occupancy_seed")
        records.append(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "temperature_k": snapshot.get("temperature_k"),
                "occupancy_seed": occupancy,
                "n_atoms": len(atoms),
                "symbols": atoms.get_chemical_symbols(),
                "dft": {
                    "total_energy_ev": completed["total_energy_ev"],
                    "forces_ev_angstrom": completed["forces_ev_angstrom"].tolist(),
                    "stress_gpa": completed["stress_gpa"].tolist(),
                },
                "model": model_label["result"],
            }
        )
        sources.append(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "dft_run_id": completed["run_id"],
                "dft_label_path": completed["label_path"],
                "dft_label_sha256": completed["label_sha256"],
                "model_label_path": str(model_path),
                "model_label_sha256": sha256_file(model_path),
            }
        )

    report = build_domain_report(records, protocol, set_id=set_id)
    report.update(
        analysis_protocol_path=str(protocol_path),
        analysis_protocol_sha256=protocol_sha256,
        snapshot_manifest_path=str(snapshots_path),
        snapshot_manifest_sha256=sha256_file(snapshots_path),
        dft_campaign_manifest_path=str(campaign_path),
        dft_campaign_manifest_sha256=sha256_file(campaign_path),
        numerical_evidence=numerical_evidence,
        selected_dft_settings=selected_settings,
        sources=sources,
    )
    report["report_fingerprint"] = fingerprint(report)
    destination = Path(out_path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite domain report: {destination}")
    atomic_write_json(destination, report)
    return report


def create_g2_release_gate(
    analysis_protocol_path: Path | str,
    *,
    domain_reports: dict[str, Path | str],
    numerical_reports: dict[str, Path | str],
    out_path: Path | str,
) -> dict[str, Any]:
    """Write a G2 pass token only when every required evidence gate passes."""
    protocol, protocol_path = load_domain_protocol(analysis_protocol_path)
    requirements = protocol["release_requirements"]
    if set(domain_reports) != set(requirements["required_domain_sets"]):
        raise ValueError("release requires exactly the frozen domain sets")
    if set(numerical_reports) != set(requirements["required_numerical_stages"]):
        raise ValueError("release requires exactly the frozen numerical stages")
    protocol_sha256 = sha256_file(protocol_path)
    evidence = []
    for set_id, value in sorted(domain_reports.items()):
        path = Path(value).resolve()
        report = _read_json(path)
        checks = {
            "report_kind": report.get("report_kind") == "chgnet-dft-domain",
            "set_id": report.get("set_id") == set_id,
            "protocol": report.get("analysis_protocol_sha256") == protocol_sha256,
            "pass": report.get("domain_gate_pass") is True,
            "claim_scope": report.get("publication_claim_gate")
            is bool(protocol["sets"][set_id]["publication_claim_gate"]),
        }
        stored_fingerprint = report.get("report_fingerprint")
        fingerprint_payload = dict(report)
        fingerprint_payload.pop("report_fingerprint", None)
        checks["fingerprint"] = stored_fingerprint == fingerprint(fingerprint_payload)
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise RuntimeError(
                f"domain report cannot release G2 ({set_id}): {', '.join(failed)}"
            )
        evidence.append(
            {"kind": f"domain:{set_id}", "path": str(path), "sha256": sha256_file(path)}
        )
    for stage, value in sorted(numerical_reports.items()):
        path = Path(value).resolve()
        report = _read_json(path)
        if report.get("numerically_converged") is not True:
            raise RuntimeError(f"numerical report cannot release G2: {stage}")
        evidence.append(
            {
                "kind": f"numerical:{stage}",
                "path": str(path),
                "sha256": sha256_file(path),
            }
        )
    gate = {
        "schema_version": "1.0",
        "gate_id": "g2-potential-domain",
        "status": "pass",
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": protocol_sha256,
        "created_unix_time": time.time(),
        "evidence": evidence,
    }
    gate["gate_fingerprint"] = fingerprint(gate)
    destination = Path(out_path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite G2 release gate: {destination}")
    atomic_write_json(destination, gate)
    return gate


def create_sampling_release_gate(
    analysis_protocol_path: Path | str,
    *,
    domain_report: Path | str,
    numerical_reports: dict[str, Path | str],
    out_path: Path | str,
) -> dict[str, Any]:
    """Authorize only short held-out sampling after feasibility has passed."""
    protocol, protocol_path = load_domain_protocol(analysis_protocol_path)
    requirements = protocol["sampling_release_requirements"]
    required_set = requirements["required_domain_set"]
    if set(numerical_reports) != set(requirements["required_numerical_stages"]):
        raise ValueError("sampling release requires every frozen numerical stage")
    protocol_sha256 = sha256_file(protocol_path)
    domain_path = Path(domain_report).resolve()
    report = _read_json(domain_path)
    fingerprint_payload = dict(report)
    stored_fingerprint = fingerprint_payload.pop("report_fingerprint", None)
    checks = {
        "report_kind": report.get("report_kind") == "chgnet-dft-domain",
        "set_id": report.get("set_id") == required_set,
        "protocol": report.get("analysis_protocol_sha256") == protocol_sha256,
        "pass": report.get("domain_gate_pass") is True,
        "development_scope": report.get("publication_claim_gate") is False,
        "fingerprint": stored_fingerprint == fingerprint(fingerprint_payload),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "feasibility report cannot release held-out sampling: "
            + ", ".join(failed)
        )
    evidence = [
        {
            "kind": f"domain:{required_set}",
            "path": str(domain_path),
            "sha256": sha256_file(domain_path),
        }
    ]
    for stage, value in sorted(numerical_reports.items()):
        path = Path(value).resolve()
        numerical = _read_json(path)
        if numerical.get("numerically_converged") is not True:
            raise RuntimeError(
                f"numerical report cannot release held-out sampling: {stage}"
            )
        evidence.append(
            {
                "kind": f"numerical:{stage}",
                "path": str(path),
                "sha256": sha256_file(path),
            }
        )
    gate = {
        "schema_version": "1.0",
        "gate_id": requirements["gate_id"],
        "status": "pass",
        "scope": requirements["scope"],
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": protocol_sha256,
        "created_unix_time": time.time(),
        "evidence": evidence,
    }
    gate["gate_fingerprint"] = fingerprint(gate)
    destination = Path(out_path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite sampling release gate: {destination}")
    atomic_write_json(destination, gate)
    return gate


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    predict = subparsers.add_parser("predict")
    predict.add_argument("snapshot_manifest")
    predict.add_argument("analysis_protocol")
    predict.add_argument("--set", required=True, dest="set_id")
    predict.add_argument("--out", required=True)
    predict.add_argument("--device", default="cpu")

    report = subparsers.add_parser("report")
    report.add_argument("snapshot_manifest")
    report.add_argument("dft_campaign_dir")
    report.add_argument("prediction_dir")
    report.add_argument("analysis_protocol")
    report.add_argument("--set", required=True, dest="set_id")
    report.add_argument(
        "--numerical-report", nargs=2, action="append", required=True
    )
    report.add_argument("--out", required=True)

    release = subparsers.add_parser("release")
    release.add_argument("analysis_protocol")
    release.add_argument("--domain-report", nargs=2, action="append", required=True)
    release.add_argument("--numerical-report", nargs=2, action="append", required=True)
    release.add_argument("--out", required=True)

    sampling = subparsers.add_parser("release-sampling")
    sampling.add_argument("analysis_protocol")
    sampling.add_argument("--domain-report", required=True)
    sampling.add_argument("--numerical-report", nargs=2, action="append", required=True)
    sampling.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.command == "predict":
        result = predict_snapshot_set(
            args.snapshot_manifest,
            args.analysis_protocol,
            set_id=args.set_id,
            out_dir=args.out,
            device=args.device,
        )
    elif args.command == "report":
        result = build_domain_report_from_files(
            args.snapshot_manifest,
            args.dft_campaign_dir,
            args.prediction_dir,
            args.analysis_protocol,
            set_id=args.set_id,
            numerical_reports=dict(args.numerical_report),
            out_path=args.out,
        )
    elif args.command == "release":
        result = create_g2_release_gate(
            args.analysis_protocol,
            domain_reports=dict(args.domain_report),
            numerical_reports=dict(args.numerical_report),
            out_path=args.out,
        )
    else:
        result = create_sampling_release_gate(
            args.analysis_protocol,
            domain_report=args.domain_report,
            numerical_reports=dict(args.numerical_report),
            out_path=args.out,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
