"""Outcome-blind, exact-composition CHGNet fine-tuning for LLZTO."""

from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path
from typing import Any

import numpy as np

from .dft import atoms_fingerprint
from .dft_convergence import load_completed_qe_run
from .mlipmd import _model_metadata
from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    sha256_file,
)


_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def validate_finetune_protocol(path: Path | str) -> tuple[dict[str, Any], Path]:
    """Validate all preregistered files that exist before fallback execution."""
    source = Path(path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("fine-tuning protocol schema_version must be '1.0'")
    if protocol.get("protocol_id") != "llzto-chgnet-finetune-contingency-v1":
        raise ValueError("unexpected fine-tuning protocol id")
    declared = [
        (
            protocol["trigger"]["universal_domain_protocol"],
            protocol["trigger"]["universal_domain_protocol_sha256"],
        ),
        (
            protocol["reference_method"]["domain_analysis_protocol"],
            protocol["reference_method"]["domain_analysis_protocol_sha256"],
        ),
        (
            protocol["bootstrap_phase"]["sources"][0]["snapshot_manifest"],
            protocol["bootstrap_phase"]["sources"][0][
                "snapshot_manifest_sha256"
            ],
        ),
        (
            protocol["expansion_phase"]["sampling_template"],
            protocol["expansion_phase"]["sampling_template_sha256"],
        ),
        (
            protocol["expansion_phase"]["snapshot_selection_protocol"],
            protocol["expansion_phase"]["snapshot_selection_protocol_sha256"],
        ),
        (
            protocol["fresh_publication_test"]["sampling_template"],
            protocol["fresh_publication_test"]["sampling_template_sha256"],
        ),
        (
            protocol["fresh_publication_test"]["snapshot_selection_protocol"],
            protocol["fresh_publication_test"][
                "snapshot_selection_protocol_sha256"
            ],
        ),
    ]
    declared.extend(
        (record["path"], record["sha256"])
        for record in protocol["implementation_locks"].values()
    )
    for value, expected in declared:
        candidate = _repo_path(value)
        if sha256_file(candidate) != expected:
            raise RuntimeError(f"declared fine-tuning hash mismatch: {candidate}")
    return protocol, source


def load_labelled_records(source_configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join snapshot coordinates to one hash-verified final-setting QE label each."""
    from ase.io import read
    from pymatgen.io.ase import AseAtomsAdaptor

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_config in source_configs:
        manifest_path = _repo_path(source_config["snapshot_manifest"])
        if source_config.get("snapshot_manifest_sha256") is not None and (
            sha256_file(manifest_path)
            != source_config["snapshot_manifest_sha256"]
        ):
            raise RuntimeError(f"training snapshot manifest changed: {manifest_path}")
        manifest = _read_json(manifest_path)
        _verify_fingerprint(
            manifest, "snapshot_set_fingerprint", "training snapshot set"
        )
        if manifest.get("selection_id") != source_config["selection_id"]:
            raise RuntimeError(f"training selection id mismatch: {manifest_path}")
        expected_selection_sha = source_config.get("selection_protocol_sha256")
        if expected_selection_sha is not None:
            selection_path = _repo_path(source_config["selection_protocol"])
            if sha256_file(selection_path) != expected_selection_sha:
                raise RuntimeError(f"training selection protocol changed: {selection_path}")
            if manifest.get("selection_protocol_sha256") != expected_selection_sha:
                raise RuntimeError(
                    f"training manifest uses another selection protocol: {manifest_path}"
                )

        campaign_root = _repo_path(source_config["dft_campaign_root"])
        campaign_path = campaign_root / "dft_campaign_manifest.json"
        campaign = _read_json(campaign_path)
        if campaign.get("snapshot_manifest_sha256") != sha256_file(manifest_path):
            raise RuntimeError("fine-tuning DFT campaign/snapshot mismatch")
        runs: dict[str, list[dict[str, Any]]] = {}
        for row in campaign.get("runs", []):
            runs.setdefault(row["snapshot_id"], []).append(row)

        for snapshot in manifest.get("snapshots", []):
            snapshot_id = str(snapshot["snapshot_id"])
            if snapshot_id in seen:
                raise ValueError(f"duplicate fine-tuning snapshot id: {snapshot_id}")
            candidates = runs.get(snapshot_id, [])
            if len(candidates) != 1:
                raise ValueError(
                    f"expected one DFT label for {snapshot_id}, found {len(candidates)}"
                )
            completed = load_completed_qe_run(
                campaign_root / candidates[0]["run_id"]
            )
            if completed["structure_fingerprint"] != snapshot["structure_fingerprint"]:
                raise RuntimeError(f"DFT structure mismatch: {snapshot_id}")
            snapshot_path = Path(snapshot["snapshot_path"]).resolve()
            if sha256_file(snapshot_path) != snapshot["snapshot_sha256"]:
                raise RuntimeError(f"training snapshot changed: {snapshot_path}")
            atoms = read(snapshot_path, index=0)
            if atoms_fingerprint(atoms) != snapshot["structure_fingerprint"]:
                raise RuntimeError(f"training snapshot fingerprint mismatch: {snapshot_id}")
            n_atoms = len(atoms)
            forces = np.asarray(completed["forces_ev_angstrom"], dtype=float)
            stress = np.asarray(completed["stress_gpa"], dtype=float)
            if forces.shape != (n_atoms, 3) or stress.shape != (3, 3):
                raise ValueError(f"invalid QE label shape: {snapshot_id}")
            if not (
                np.isfinite(forces).all()
                and np.isfinite(stress).all()
                and math.isfinite(float(completed["total_energy_ev"]))
            ):
                raise ValueError(f"non-finite QE label: {snapshot_id}")
            metadata = snapshot.get("metadata") or {}
            records.append(
                {
                    "snapshot_id": snapshot_id,
                    "source_selection_id": manifest["selection_id"],
                    "temperature_k": snapshot.get("temperature_k"),
                    "occupancy_seed": metadata.get("occupancy_seed", 0),
                    "n_atoms": n_atoms,
                    "structure": AseAtomsAdaptor.get_structure(atoms),
                    "energy_per_atom_ev": float(completed["total_energy_ev"])
                    / n_atoms,
                    "forces_ev_angstrom": forces,
                    "stress_positive_tension_gpa": stress,
                    "source": {
                        "snapshot_path": str(snapshot_path),
                        "snapshot_sha256": snapshot["snapshot_sha256"],
                        "structure_fingerprint": snapshot["structure_fingerprint"],
                        "dft_run_id": completed["run_id"],
                        "dft_label_path": completed["label_path"],
                        "dft_label_sha256": completed["label_sha256"],
                    },
                }
            )
            seen.add(snapshot_id)
    return records


def resolve_phase_split(
    records: list[dict[str, Any]], phase: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Resolve either the explicit bootstrap split or final Latin diagonal."""
    all_ids = {str(record["snapshot_id"]) for record in records}
    if len(all_ids) != len(records):
        raise ValueError("fine-tuning record IDs are not unique")
    if len(records) != int(phase["expected_records"]):
        raise ValueError(
            f"expected {phase['expected_records']} fine-tuning records, got {len(records)}"
        )
    if "validation_ids" in phase:
        validation = set(map(str, phase["validation_ids"]))
    else:
        rule = phase.get("validation_rule", {})
        if rule.get("kind") != "latin-diagonal-entire-occupancy-temperature-strata":
            raise ValueError("unknown final fine-tuning validation rule")
        mapping = {
            int(occupancy): int(temperature)
            for occupancy, temperature in rule["occupancy_to_temperature_k"].items()
        }
        validation = {
            str(record["snapshot_id"])
            for record in records
            if record["source_selection_id"] == "llzto-finetune-training-v1"
            and mapping.get(int(record["occupancy_seed"]))
            == int(record["temperature_k"])
        }
        if len(validation) != int(rule["expected_validation_records"]):
            raise ValueError("final fine-tuning validation-stratum count differs")
    if not validation or not validation.issubset(all_ids):
        raise ValueError("fine-tuning validation IDs are missing")
    training = all_ids - validation
    if not training or training & validation or training | validation != all_ids:
        raise AssertionError("fine-tuning split is not a disjoint partition")
    return sorted(training), sorted(validation)


def qe_stress_to_structure_data(stress_gpa: Any) -> np.ndarray:
    """Convert positive-tension GPa to the VASP-style kbar expected by CHGNet."""
    values = np.asarray(stress_gpa, dtype=float)
    if values.shape != (3, 3) or not np.isfinite(values).all():
        raise ValueError("fine-tuning stress must be a finite 3 x 3 tensor")
    return -10.0 * values


def _composition_fraction(structures: list[Any]) -> np.ndarray:
    fractions = []
    for structure in structures:
        vector = np.zeros(94, dtype=float)
        for site in structure:
            vector[int(site.specie.Z) - 1] += 1.0
        vector /= len(structure)
        fractions.append(vector)
    reference = fractions[0]
    if any(not np.array_equal(value, reference) for value in fractions[1:]):
        raise ValueError("AtomRef alignment requires one exact composition")
    return reference


def align_atomref_minimum_l2(model: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Align the fixed-composition energy reference with a minimum-L2 shift."""
    import torch

    if not records:
        raise ValueError("AtomRef alignment has no records")
    composition_model = getattr(model, "composition_model", None)
    weight_parameter = getattr(getattr(composition_model, "fc", None), "weight", None)
    if weight_parameter is None or tuple(weight_parameter.shape) != (1, 94):
        raise TypeError("fine-tuning requires the pretrained 94-element AtomRef")
    structures = [record["structure"] for record in records]
    fraction = _composition_fraction(structures)
    old_weight = weight_parameter.detach().cpu().numpy().reshape(94).astype(float)
    old_contribution = float(np.dot(fraction, old_weight))
    predictions = [
        float(np.asarray(model.predict_structure(structure, task="e")["e"]).reshape(()))
        for structure in structures
    ]
    interactions = np.asarray(predictions, dtype=float) - old_contribution
    targets = np.asarray(
        [record["energy_per_atom_ev"] for record in records], dtype=float
    )
    target_contribution = float(np.mean(targets) - np.mean(interactions))
    norm = float(np.dot(fraction, fraction))
    if norm <= 0:
        raise ValueError("composition fraction vector is empty")
    delta = fraction * ((target_contribution - old_contribution) / norm)
    new_weight = old_weight + delta
    with torch.no_grad():
        weight_parameter.copy_(
            torch.as_tensor(
                new_weight.reshape(1, 94),
                dtype=weight_parameter.dtype,
                device=weight_parameter.device,
            )
        )
    for parameter in composition_model.parameters():
        parameter.requires_grad = False
    aligned = [
        float(np.asarray(model.predict_structure(structure, task="e")["e"]).reshape(()))
        for structure in structures
    ]
    residual = float(np.mean(aligned) - np.mean(targets))
    if abs(residual) > 2e-5:
        raise RuntimeError(f"AtomRef mean alignment residual is {residual:g} eV/atom")
    return {
        "method": "minimum-L2 fixed-composition AtomRef shift",
        "n_records": len(records),
        "old_composition_contribution_ev_atom": old_contribution,
        "target_composition_contribution_ev_atom": target_contribution,
        "weight_shift_l2_ev_atom": float(np.linalg.norm(delta)),
        "mean_dft_energy_ev_atom": float(np.mean(targets)),
        "mean_pretrained_interaction_ev_atom": float(np.mean(interactions)),
        "post_alignment_mean_residual_ev_atom": residual,
        "composition_fraction_by_atomic_number": {
            str(index + 1): float(value)
            for index, value in enumerate(fraction)
            if value > 0
        },
    }


def freeze_transfer_layers(model: Any) -> dict[str, Any]:
    """Apply the frozen-layer scope from the official CHGNet tuning example."""
    for parameter in model.parameters():
        parameter.requires_grad = True
    layers = [
        model.atom_embedding,
        model.bond_embedding,
        model.angle_embedding,
        model.bond_basis_expansion,
        model.angle_basis_expansion,
        *list(model.atom_conv_layers[:-1]),
        *list(model.bond_conv_layers),
        *list(model.angle_layers),
        model.composition_model,
    ]
    for layer in layers:
        for parameter in layer.parameters():
            parameter.requires_grad = False
    trainable = [name for name, value in model.named_parameters() if value.requires_grad]
    frozen = [name for name, value in model.named_parameters() if not value.requires_grad]
    if not trainable or not frozen:
        raise RuntimeError("fine-tuning layer freeze produced an empty parameter scope")
    return {
        "trainable_parameter_names": trainable,
        "frozen_parameter_names": frozen,
        "n_trainable_parameters": int(
            sum(value.numel() for value in model.parameters() if value.requires_grad)
        ),
        "n_frozen_parameters": int(
            sum(value.numel() for value in model.parameters() if not value.requires_grad)
        ),
    }


def normalized_validation_score(
    metrics: dict[str, float], normalizers: dict[str, float]
) -> float:
    """Return the frozen worst-normalized validation MAE."""
    if set(normalizers) != {"e", "f", "s"}:
        raise ValueError("fine-tuning checkpoint normalizers must be e/f/s")
    values = []
    for key in ("e", "f", "s"):
        metric = float(metrics[key])
        scale = float(normalizers[key])
        if not math.isfinite(metric) or metric < 0 or scale <= 0:
            raise ValueError("fine-tuning validation score input is invalid")
        values.append(metric / scale)
    return float(max(values))


def _make_loader(
    records: list[dict[str, Any]],
    selected_ids: list[str],
    *,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> Any:
    import torch
    from chgnet.data.dataset import StructureData, collate_graphs
    from torch.utils.data import DataLoader, Subset

    dataset = StructureData(
        structures=[record["structure"] for record in records],
        energies=[record["energy_per_atom_ev"] for record in records],
        forces=[record["forces_ev_angstrom"] for record in records],
        stresses=[
            qe_stress_to_structure_data(record["stress_positive_tension_gpa"])
            for record in records
        ],
        structure_ids=[record["snapshot_id"] for record in records],
        shuffle=False,
    )
    index = {record["snapshot_id"]: position for position, record in enumerate(records)}
    subset = Subset(dataset, [index[value] for value in selected_ids])
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        subset,
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=collate_graphs,
        num_workers=0,
        pin_memory=False,
        generator=generator,
    )


def _new_trainer(model: Any, config: dict[str, Any], phase: dict[str, Any], device: str) -> Any:
    from chgnet.trainer import Trainer

    return Trainer(
        model=model,
        targets=config["targets"],
        optimizer=config["optimizer"],
        scheduler=config["scheduler"],
        criterion=config["criterion"],
        epochs=int(phase["max_epochs"]),
        learning_rate=float(config["learning_rate"]),
        energy_loss_ratio=float(config["energy_loss_ratio"]),
        force_loss_ratio=float(config["force_loss_ratio"]),
        stress_loss_ratio=float(config["stress_loss_ratio"]),
        torch_seed=int(phase["torch_seed"]),
        data_seed=int(phase["data_seed"]),
        use_device=device,
        print_freq=10_000,
        allow_missing_labels=False,
    )


def train_finetune_phase(
    protocol_path: Path | str,
    *,
    phase_name: str,
    device: str = "cuda",
) -> dict[str, Any]:
    """Select an epoch without heldout labels, refit all records, and save a model."""
    import torch
    from chgnet.model import CHGNet

    protocol, source = validate_finetune_protocol(protocol_path)
    if phase_name not in {"bootstrap_phase", "final_training_phase"}:
        raise ValueError("phase_name must be bootstrap_phase or final_training_phase")
    if device not in {"cpu", "cuda", "mps"}:
        raise ValueError("fine-tuning device must be cpu, cuda, or mps")
    phase = protocol[phase_name]
    records = load_labelled_records(phase["sources"])
    training_ids, validation_ids = resolve_phase_split(records, phase)
    by_id = {record["snapshot_id"]: record for record in records}
    training_records = [by_id[value] for value in training_ids]
    training_config = protocol["transfer_learning"]
    batch_size = int(training_config["batch_size"])
    model_path = _repo_path(phase["output_model"])
    report_path = _repo_path(phase["output_report"])
    if model_path.exists() or report_path.exists():
        raise RuntimeError(f"refusing to overwrite fine-tuning phase {phase_name}")
    model_path.parent.mkdir(parents=True, exist_ok=True)

    random.seed(int(phase["data_seed"]))
    np.random.seed(int(phase["data_seed"]))
    torch.manual_seed(int(phase["torch_seed"]))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(phase["torch_seed"]))

    selection_model = CHGNet.load(verbose=False, use_device="cpu")
    baseline_metadata = _model_metadata(selection_model, "CHGNet-default")
    if (
        baseline_metadata["state_dict_sha256"]
        != protocol["baseline_model"]["state_dict_sha256"]
    ):
        raise RuntimeError("fine-tuning baseline weights differ from the protocol")
    selection_alignment = align_atomref_minimum_l2(
        selection_model, training_records
    )
    parameter_scope = freeze_transfer_layers(selection_model)
    train_loader = _make_loader(
        records,
        training_ids,
        batch_size=batch_size,
        shuffle=True,
        seed=int(phase["data_seed"]),
    )
    validation_loader = _make_loader(
        records,
        validation_ids,
        batch_size=batch_size,
        shuffle=False,
        seed=int(phase["data_seed"]),
    )
    trainer = _new_trainer(selection_model, training_config, phase, device)
    selection_model.to(trainer.device)
    history = []
    best_score = float("inf")
    best_epoch = -1
    best_state = None
    for epoch in range(int(phase["max_epochs"])):
        train_metrics = trainer._train(train_loader, epoch, "epoch")
        validation_metrics = trainer._validate(
            validation_loader, is_test=False, wandb_log_freq="epoch"
        )
        score = normalized_validation_score(
            validation_metrics, training_config["checkpoint_normalizers"]
        )
        history.append(
            {
                "epoch": epoch,
                "train_mae": train_metrics,
                "validation_mae": validation_metrics,
                "normalized_worst_validation_score": score,
            }
        )
        if score < best_score:
            best_score = score
            best_epoch = epoch
            best_state = copy.deepcopy(selection_model.state_dict())
    if best_state is None or best_epoch < 0:
        raise RuntimeError("fine-tuning did not produce a finite checkpoint")

    final_model = CHGNet.load(verbose=False, use_device="cpu")
    refit_alignment = align_atomref_minimum_l2(final_model, records)
    refit_scope = freeze_transfer_layers(final_model)
    if refit_scope != parameter_scope:
        raise RuntimeError("fine-tuning trainable scope changed between selection/refit")
    refit_loader = _make_loader(
        records,
        sorted(by_id),
        batch_size=batch_size,
        shuffle=True,
        seed=int(phase["data_seed"]),
    )
    refit_trainer = _new_trainer(final_model, training_config, phase, device)
    final_model.to(refit_trainer.device)
    refit_history = []
    for epoch in range(best_epoch + 1):
        refit_history.append(
            {
                "epoch": epoch,
                "train_mae": refit_trainer._train(refit_loader, epoch, "epoch"),
            }
        )
    final_model.to("cpu")
    artifact = {
        "model": final_model.as_dict(),
        "training_protocol_path": str(source),
        "training_protocol_sha256": sha256_file(source),
        "training_phase": phase_name,
    }
    torch.save(artifact, model_path)
    reloaded = CHGNet.from_file(str(model_path))
    final_metadata = _model_metadata(reloaded, f"LLZTO-{phase_name}-v1")
    sources = [
        {
            "snapshot_id": record["snapshot_id"],
            **record["source"],
        }
        for record in records
    ]
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "report_kind": "chgnet-fine-tuning",
        "phase": phase_name,
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "baseline_model": baseline_metadata,
        "training_ids": training_ids,
        "validation_ids": validation_ids,
        "n_training_records": len(training_ids),
        "n_validation_records": len(validation_ids),
        "n_refit_records": len(records),
        "selection_alignment": selection_alignment,
        "refit_alignment": refit_alignment,
        "parameter_scope": parameter_scope,
        "training_configuration": training_config,
        "checkpoint_selection": {
            "selected_epoch_zero_based": best_epoch,
            "selected_epoch_count": best_epoch + 1,
            "normalized_worst_validation_score": best_score,
            "selected_validation_mae": history[best_epoch]["validation_mae"],
            "selection_model_state_retained": False,
            "hard_rule": "The selected state chooses only epoch count; the saved model is a fresh refit on every non-heldout record.",
        },
        "selection_history": history,
        "refit_history": refit_history,
        "model_artifact": {
            "path": str(model_path),
            "sha256": sha256_file(model_path),
            "state_dict_sha256": final_metadata["state_dict_sha256"],
            "metadata": final_metadata,
        },
        "sources": sources,
        "environment": environment_versions(
            ("matfactory", "chgnet", "torch", "numpy", "ase", "pymatgen")
        ),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
        "fresh_publication_heldout_labels_read": False,
    }
    report["report_fingerprint"] = fingerprint(report)
    atomic_write_json(report_path, report)
    return report


def derive_model_campaign(
    template_path: Path | str,
    training_report_path: Path | str,
    *,
    out_path: Path | str,
    configured_model_name: str,
) -> dict[str, Any]:
    """Derive one campaign by filling only a completed model's locked identity."""
    from chgnet.model import CHGNet

    template_source = Path(template_path).resolve()
    report_source = Path(training_report_path).resolve()
    template = _read_json(template_source)
    report = _read_json(report_source)
    _verify_fingerprint(report, "report_fingerprint", "fine-tuning report")
    if report.get("report_kind") != "chgnet-fine-tuning":
        raise ValueError("campaign derivation requires a fine-tuning report")
    artifact = report.get("model_artifact", {})
    model_path = Path(artifact["path"]).resolve()
    if sha256_file(model_path) != artifact.get("sha256"):
        raise RuntimeError("fine-tuned model artifact hash mismatch")
    model = CHGNet.from_file(str(model_path))
    observed = _model_metadata(model, configured_model_name)
    if observed["state_dict_sha256"] != artifact.get("state_dict_sha256"):
        raise RuntimeError("fine-tuned model state dictionary mismatch")
    base = template.get("base_config", {})
    if (
        base.get("expected_model_state_dict_sha256") is not None
        or not str(base.get("model_name", "")).startswith("DERIVE_FROM_")
    ):
        raise RuntimeError("campaign template already contains a model identity")
    if not configured_model_name or configured_model_name == "CHGNet-default":
        raise ValueError("derived model name must distinguish the fine-tuned model")
    derived = copy.deepcopy(template)
    derived["base_config"]["model_name"] = configured_model_name
    derived["base_config"]["expected_model_state_dict_sha256"] = observed[
        "state_dict_sha256"
    ]
    derived["derived_model_artifact"] = {
        "path": str(model_path),
        "sha256": sha256_file(model_path),
        "state_dict_sha256": observed["state_dict_sha256"],
        "training_report_path": str(report_source),
        "training_report_sha256": sha256_file(report_source),
        "training_report_fingerprint": report["report_fingerprint"],
    }
    derived["derivation"] = {
        "template_path": str(template_source),
        "template_sha256": sha256_file(template_source),
        "allowed_changes": [
            "base_config.model_name",
            "base_config.expected_model_state_dict_sha256",
            "derived_model_artifact",
            "derivation",
            "derivation_fingerprint",
        ],
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    derived["derivation_fingerprint"] = fingerprint(derived)
    destination = Path(out_path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite derived campaign: {destination}")
    atomic_write_json(destination, derived)
    from .campaign import load_campaign

    campaign = load_campaign(destination)
    return {
        "path": str(destination),
        "sha256": campaign.protocol_sha256,
        "campaign_id": campaign.campaign_id,
        "n_runs": len(campaign.runs),
        "model_artifact_sha256": sha256_file(model_path),
        "model_state_dict_sha256": observed["state_dict_sha256"],
        "derivation_fingerprint": derived["derivation_fingerprint"],
    }


def create_training_release_gate(
    training_report_path: Path | str,
    *,
    gate_id: str,
    out_path: Path | str,
) -> dict[str, Any]:
    """Release only coordinate sampling associated with one completed model."""
    if gate_id not in {"g2-finetune-bootstrap", "g2-finetune-final-model"}:
        raise ValueError("unknown fine-tuning model release gate")
    report_path = Path(training_report_path).resolve()
    report = _read_json(report_path)
    _verify_fingerprint(report, "report_fingerprint", "fine-tuning report")
    expected_phase = {
        "g2-finetune-bootstrap": "bootstrap_phase",
        "g2-finetune-final-model": "final_training_phase",
    }[gate_id]
    if (
        report.get("report_kind") != "chgnet-fine-tuning"
        or report.get("phase") != expected_phase
        or report.get("fresh_publication_heldout_labels_read") is not False
    ):
        raise RuntimeError("fine-tuning report cannot release this sampling gate")
    artifact = report.get("model_artifact", {})
    artifact_path = Path(artifact["path"]).resolve()
    if sha256_file(artifact_path) != artifact.get("sha256"):
        raise RuntimeError("fine-tuning release model artifact changed")
    gate: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": gate_id,
        "status": "pass",
        "scope": "coordinate sampling only; no transport or publication claim",
        "model_state_dict_sha256": artifact["state_dict_sha256"],
        "evidence": [
            {
                "kind": "fine-tuning-report",
                "path": str(report_path),
                "sha256": sha256_file(report_path),
            },
            {
                "kind": "model-artifact",
                "path": str(artifact_path),
                "sha256": sha256_file(artifact_path),
            },
        ],
    }
    gate["gate_fingerprint"] = fingerprint(gate)
    destination = Path(out_path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite model release gate: {destination}")
    atomic_write_json(destination, gate)
    return gate


def derive_finetuned_domain_protocol(
    base_protocol_path: Path | str,
    training_report_path: Path | str,
    selection_protocol_path: Path | str,
    *,
    out_path: Path | str,
) -> dict[str, Any]:
    """Freeze the final model identity while retaining every original threshold."""
    from chgnet.model import CHGNet

    base_path = Path(base_protocol_path).resolve()
    report_path = Path(training_report_path).resolve()
    selection_path = Path(selection_protocol_path).resolve()
    base = _read_json(base_path)
    report = _read_json(report_path)
    selection = _read_json(selection_path)
    _verify_fingerprint(report, "report_fingerprint", "final fine-tuning report")
    if (
        report.get("phase") != "final_training_phase"
        or report.get("fresh_publication_heldout_labels_read") is not False
    ):
        raise RuntimeError("only the label-blind final training phase can be derived")
    if selection.get("selection_id") != "llzto-finetune-fresh-heldout-v1":
        raise RuntimeError("wrong fresh-heldout selection protocol")
    artifact = report["model_artifact"]
    model_path = Path(artifact["path"]).resolve()
    if sha256_file(model_path) != artifact["sha256"]:
        raise RuntimeError("final fine-tuned model artifact changed")
    model = CHGNet.from_file(str(model_path))
    metadata = _model_metadata(model, "LLZTO-CHGNet-finetuned-v1")
    if metadata["state_dict_sha256"] != artifact["state_dict_sha256"]:
        raise RuntimeError("final fine-tuned state dictionary changed")
    derived = copy.deepcopy(base)
    derived["protocol_id"] = "llzto-chgnet-finetuned-domain-v1"
    derived["model"].update(
        name="LLZTO-CHGNet-finetuned-v1",
        expected_state_dict_sha256=artifact["state_dict_sha256"],
    )
    derived["blinding"] = {
        "training": "The 62 training/development records were frozen without any fresh-heldout label.",
        "publication_test": "Thirty independent-seed 5-by-6 occupancy-temperature snapshots are used once and never train or select the model.",
        "thresholds": "Aggregate and robustness limits are byte-for-byte copied from the universal-domain protocol before any fallback result.",
    }
    derived["sets"] = {
        "fine-tuned-publication-heldout": {
            "selection_id": "llzto-finetune-fresh-heldout-v1",
            "expected_snapshots": 30,
            "required_temperature_strata_k": [650, 700, 750, 800, 850, 900],
            "required_occupancy_seeds": [0, 1, 2, 3, 4],
            "publication_claim_gate": True,
        }
    }
    derived.pop("sampling_release_requirements", None)
    derived["release_requirements"] = {
        "required_domain_sets": ["fine-tuned-publication-heldout"],
        "required_numerical_stages": ["cutoff", "kpoint", "scf"],
        "failure_action": "Do not release or publish fine-tuned-model transport; preserve the failed fallback and narrow or withdraw the computational claim.",
    }
    derived["derivation"] = {
        "base_protocol_path": str(base_path),
        "base_protocol_sha256": sha256_file(base_path),
        "training_report_path": str(report_path),
        "training_report_sha256": sha256_file(report_path),
        "model_artifact_path": str(model_path),
        "model_artifact_sha256": sha256_file(model_path),
        "selection_protocol_path": str(selection_path),
        "selection_protocol_sha256": sha256_file(selection_path),
        "unchanged_aggregate_limits": derived["aggregate_limits"]
        == base["aggregate_limits"],
        "unchanged_robustness_limits": derived["robustness_limits"]
        == base["robustness_limits"],
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    if not (
        derived["derivation"]["unchanged_aggregate_limits"]
        and derived["derivation"]["unchanged_robustness_limits"]
    ):
        raise AssertionError("fine-tuned domain thresholds changed")
    derived["derivation_fingerprint"] = fingerprint(derived)
    destination = Path(out_path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite derived domain protocol: {destination}")
    atomic_write_json(destination, derived)
    from .dft_domain import load_domain_protocol

    loaded, _ = load_domain_protocol(destination)
    return {
        "path": str(destination),
        "sha256": sha256_file(destination),
        "protocol_id": loaded["protocol_id"],
        "model_state_dict_sha256": artifact["state_dict_sha256"],
        "derivation_fingerprint": derived["derivation_fingerprint"],
    }


def predict_snapshot_set_custom(
    snapshot_manifest_path: Path | str,
    analysis_protocol_path: Path | str,
    model_artifact_path: Path | str,
    *,
    set_id: str,
    out_dir: Path | str,
    device: str = "cpu",
) -> dict[str, Any]:
    """Create immutable fine-tuned labels without falling back to CHGNet.load."""
    from ase.io import read
    from chgnet.model import CHGNet
    from pymatgen.io.ase import AseAtomsAdaptor

    from .dft_domain import (
        _load_snapshot_set,
        _verify_prediction_label,
        load_domain_protocol,
    )

    protocol, protocol_path = load_domain_protocol(analysis_protocol_path)
    if set_id not in protocol["sets"]:
        raise ValueError(f"unknown fine-tuned domain set {set_id!r}")
    snapshots, snapshots_path = _load_snapshot_set(
        snapshot_manifest_path, set_config=protocol["sets"][set_id]
    )
    artifact_path = Path(model_artifact_path).resolve()
    model = CHGNet.from_file(str(artifact_path)).to(device)
    model_metadata = _model_metadata(model, protocol["model"]["name"])
    expected_model_sha = protocol["model"]["expected_state_dict_sha256"]
    if model_metadata["state_dict_sha256"] != expected_model_sha:
        raise RuntimeError("custom prediction model differs from domain protocol")
    if bool(model.is_intensive) != bool(protocol["model"]["energy_is_intensive"]):
        raise RuntimeError("custom prediction energy extensivity differs")
    environment = environment_versions(
        ("matfactory", "chgnet", "torch", "ase", "pymatgen", "numpy")
    )
    if environment["packages"]["chgnet"] != protocol["model"]["package_version"]:
        raise RuntimeError("custom prediction CHGNet package differs")
    destination = Path(out_dir).resolve()
    labels_dir = destination / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    protocol_sha = sha256_file(protocol_path)
    rows = []
    for snapshot in snapshots["snapshots"]:
        snapshot_path = Path(snapshot["snapshot_path"]).resolve()
        if sha256_file(snapshot_path) != snapshot["snapshot_sha256"]:
            raise RuntimeError(f"fresh-heldout snapshot changed: {snapshot_path}")
        atoms = read(snapshot_path, index=0)
        if atoms_fingerprint(atoms) != snapshot["structure_fingerprint"]:
            raise RuntimeError(f"fresh-heldout structure changed: {snapshot['snapshot_id']}")
        label_path = labels_dir / f"{snapshot['snapshot_id']}.json"
        if label_path.exists():
            label = _read_json(label_path)
            _verify_prediction_label(
                label,
                snapshot=snapshot,
                protocol_sha256=protocol_sha,
                expected_model_sha256=expected_model_sha,
                expected_package_version=protocol["model"]["package_version"],
            )
            if label.get("model_artifact_sha256") != sha256_file(artifact_path):
                raise RuntimeError("existing custom label uses another artifact")
        else:
            structure = AseAtomsAdaptor.get_structure(atoms)
            prediction = model.predict_structure(structure, task="efs")
            energy = float(np.asarray(prediction["e"]).reshape(()))
            forces = np.asarray(prediction["f"], dtype=float)
            stress = np.asarray(prediction["s"], dtype=float)
            if forces.shape != (len(atoms), 3) or stress.shape != (3, 3):
                raise RuntimeError("fine-tuned CHGNet returned invalid label shapes")
            label = {
                "schema_version": "1.0",
                "label_kind": "chgnet-single-point",
                "set_id": set_id,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_path": str(snapshot_path),
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "structure_fingerprint": snapshot["structure_fingerprint"],
                "n_atoms": len(atoms),
                "symbols": atoms.get_chemical_symbols(),
                "analysis_protocol_path": str(protocol_path),
                "analysis_protocol_sha256": protocol_sha,
                "prediction_implementation_path": str(Path(__file__).resolve()),
                "prediction_implementation_sha256": sha256_file(__file__),
                "model_artifact_path": str(artifact_path),
                "model_artifact_sha256": sha256_file(artifact_path),
                "model": {
                    **model_metadata,
                    "package_version_required": protocol["model"][
                        "package_version"
                    ],
                    "energy_is_intensive": bool(model.is_intensive),
                    "device": device,
                },
                "environment": environment,
                "result": {
                    "total_energy_ev": energy * len(atoms)
                    if model.is_intensive
                    else energy,
                    "forces_ev_angstrom": forces.tolist(),
                    "stress_gpa": stress.tolist(),
                    "stress_convention": protocol["model"]["stress_convention"],
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
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "set_id": set_id,
        "snapshot_manifest_path": str(snapshots_path),
        "snapshot_manifest_sha256": sha256_file(snapshots_path),
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": protocol_sha,
        "model_artifact_path": str(artifact_path),
        "model_artifact_sha256": sha256_file(artifact_path),
        "model_state_dict_sha256": expected_model_sha,
        "n_predictions": len(rows),
        "predictions": rows,
    }
    manifest["prediction_manifest_fingerprint"] = fingerprint(manifest)
    manifest_path = destination / "prediction_manifest.json"
    if manifest_path.exists():
        if _read_json(manifest_path) != manifest:
            raise RuntimeError("existing custom prediction manifest differs")
    else:
        atomic_write_json(manifest_path, manifest)
    return manifest


def create_finetuned_g2_release_gate(
    analysis_protocol_path: Path | str,
    domain_report_path: Path | str,
    training_report_path: Path | str,
    *,
    numerical_reports: dict[str, Path | str],
    gate_id: str,
    out_path: Path | str,
) -> dict[str, Any]:
    """Release only the passed final model and never the universal campaigns."""
    protocol_path = Path(analysis_protocol_path).resolve()
    domain_path = Path(domain_report_path).resolve()
    training_path = Path(training_report_path).resolve()
    protocol = _read_json(protocol_path)
    domain = _read_json(domain_path)
    training = _read_json(training_path)
    _verify_fingerprint(domain, "report_fingerprint", "fine-tuned domain report")
    _verify_fingerprint(training, "report_fingerprint", "final fine-tuning report")
    expected_set = "fine-tuned-publication-heldout"
    checks = {
        "domain_kind": domain.get("report_kind") == "chgnet-dft-domain",
        "domain_set": domain.get("set_id") == expected_set,
        "domain_protocol": domain.get("analysis_protocol_sha256")
        == sha256_file(protocol_path),
        "domain_pass": domain.get("domain_gate_pass") is True,
        "publication_scope": domain.get("publication_claim_gate") is True,
        "training_phase": training.get("phase") == "final_training_phase",
        "heldout_not_read_for_training": training.get(
            "fresh_publication_heldout_labels_read"
        )
        is False,
        "model_identity": protocol.get("model", {}).get(
            "expected_state_dict_sha256"
        )
        == training.get("model_artifact", {}).get("state_dict_sha256"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("fine-tuned G2 release failed: " + ", ".join(failed))
    required_numerical = {"cutoff", "kpoint", "scf"}
    if set(numerical_reports) != required_numerical:
        raise ValueError("fine-tuned G2 requires cutoff, kpoint, and SCF evidence")
    evidence = [
        {"kind": "fine-tuned-domain", "path": str(domain_path), "sha256": sha256_file(domain_path)},
        {"kind": "fine-tuning-report", "path": str(training_path), "sha256": sha256_file(training_path)},
    ]
    for stage, value in sorted(numerical_reports.items()):
        path = Path(value).resolve()
        report = _read_json(path)
        if report.get("numerically_converged") is not True:
            raise RuntimeError(f"fine-tuned G2 numerical stage failed: {stage}")
        evidence.append(
            {"kind": f"numerical:{stage}", "path": str(path), "sha256": sha256_file(path)}
        )
    gate: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_id": gate_id,
        "status": "pass",
        "scope": "fine-tuned exact-composition LLZTO campaigns only",
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": sha256_file(protocol_path),
        "model_state_dict_sha256": protocol["model"][
            "expected_state_dict_sha256"
        ],
        "universal_g2_token_created": False,
        "evidence": evidence,
    }
    gate["gate_fingerprint"] = fingerprint(gate)
    destination = Path(out_path).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite fine-tuned G2 gate: {destination}")
    atomic_write_json(destination, gate)
    return gate


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument(
        "--phase", choices=("bootstrap_phase", "final_training_phase"), required=True
    )
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    report = train_finetune_phase(
        args.protocol,
        phase_name=args.phase,
        device=args.device,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
