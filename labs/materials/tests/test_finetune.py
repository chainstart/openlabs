from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.campaign import load_campaign  # noqa: E402
from matfactory.custom_campaign import (  # noqa: E402
    run_custom_campaign,
    validate_custom_campaign,
)
from matfactory.finetune_queue import run_finetune_contingency_queue  # noqa: E402
from matfactory.model_md_queue import run_model_md_queue  # noqa: E402
from matfactory.dft import atoms_fingerprint  # noqa: E402
from matfactory.finetune import (  # noqa: E402
    align_atomref_minimum_l2,
    create_training_release_gate,
    create_finetuned_g2_release_gate,
    derive_finetuned_domain_protocol,
    derive_model_campaign,
    freeze_transfer_layers,
    load_labelled_records,
    normalized_validation_score,
    predict_snapshot_set_custom,
    qe_stress_to_structure_data,
    resolve_phase_split,
    validate_finetune_protocol,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_qe_stress_conversion_round_trips_chgnet_structure_data_units():
    positive_tension_gpa = np.array(
        [[1.0, 0.2, -0.3], [0.2, -2.0, 0.4], [-0.3, 0.4, 3.0]]
    )
    vasp_style_kbar = qe_stress_to_structure_data(positive_tension_gpa)

    assert vasp_style_kbar == pytest.approx(-10.0 * positive_tension_gpa)
    assert -0.1 * vasp_style_kbar == pytest.approx(positive_tension_gpa)


def test_checkpoint_score_uses_the_worst_normalized_target():
    score = normalized_validation_score(
        {"e": 0.0075, "f": 0.12, "s": 0.10},
        {"e": 0.015, "f": 0.10, "s": 0.25},
    )
    assert score == pytest.approx(1.2)


def test_bootstrap_and_final_splits_are_disjoint_and_label_blind():
    bootstrap_ids = [
        "relaxed-occ00",
        *[f"pilot-t700-0{index}" for index in range(3)],
        *[f"pilot-t800-0{index}" for index in range(4)],
        *[f"pilot-t900-0{index}" for index in range(4)],
    ]
    bootstrap_records = [
        {
            "snapshot_id": value,
            "source_selection_id": "llzto-dft-feasibility-v1",
            "occupancy_seed": 0,
            "temperature_k": None,
        }
        for value in bootstrap_ids
    ]
    bootstrap_phase = {
        "expected_records": 12,
        "validation_ids": [
            "relaxed-occ00",
            "pilot-t700-01",
            "pilot-t800-01",
            "pilot-t900-02",
        ],
    }
    training, validation = resolve_phase_split(bootstrap_records, bootstrap_phase)
    assert len(training) == 8
    assert len(validation) == 4
    assert set(training).isdisjoint(validation)

    final_records = list(bootstrap_records)
    temperatures = [700, 750, 800, 850, 900]
    for occupancy in range(5):
        for temperature in temperatures:
            for ordinal in range(2):
                final_records.append(
                    {
                        "snapshot_id": (
                            f"finetune-train-occ{occupancy:02d}-t{temperature}-"
                            f"{ordinal:02d}"
                        ),
                        "source_selection_id": "llzto-finetune-training-v1",
                        "occupancy_seed": occupancy,
                        "temperature_k": temperature,
                    }
                )
    final_phase = {
        "expected_records": 62,
        "validation_rule": {
            "kind": "latin-diagonal-entire-occupancy-temperature-strata",
            "occupancy_to_temperature_k": {
                "0": 700,
                "1": 750,
                "2": 800,
                "3": 850,
                "4": 900,
            },
            "expected_validation_records": 10,
        },
    }
    final_training, final_validation = resolve_phase_split(final_records, final_phase)
    assert len(final_training) == 52
    assert len(final_validation) == 10
    assert all(value.startswith("finetune-train-") for value in final_validation)
    assert set(bootstrap_ids).issubset(final_training)


def test_label_loader_joins_exactly_one_hash_verified_qe_result(tmp_path, monkeypatch):
    from ase import Atoms
    from ase.io import write

    atoms = Atoms(
        symbols=["Li", "Li", "O"],
        scaled_positions=[[0, 0, 0], [0.25, 0.25, 0.25], [0.6, 0.6, 0.6]],
        cell=np.eye(3) * 8.0,
        pbc=True,
    )
    snapshot_path = tmp_path / "snapshot.extxyz"
    write(snapshot_path, atoms, format="extxyz")
    stored = __import__("ase.io", fromlist=["read"]).read(snapshot_path, index=0)
    structure_fingerprint = atoms_fingerprint(stored)
    manifest = {
        "schema_version": "1.0",
        "selection_id": "synthetic-selection",
        "n_snapshots": 1,
        "snapshots": [
            {
                "snapshot_id": "synthetic-00",
                "snapshot_path": str(snapshot_path),
                "snapshot_sha256": sha256_file(snapshot_path),
                "structure_fingerprint": structure_fingerprint,
                "temperature_k": 800,
                "metadata": {"occupancy_seed": 2},
            }
        ],
    }
    manifest["snapshot_set_fingerprint"] = fingerprint(manifest)
    manifest_path = tmp_path / "snapshot-manifest.json"
    _write_json(manifest_path, manifest)
    campaign_root = tmp_path / "dft"
    _write_json(
        campaign_root / "dft_campaign_manifest.json",
        {
            "snapshot_manifest_sha256": sha256_file(manifest_path),
            "runs": [{"snapshot_id": "synthetic-00", "run_id": "qe-run-00"}],
        },
    )

    monkeypatch.setattr(
        "matfactory.finetune.load_completed_qe_run",
        lambda _: {
            "run_id": "qe-run-00",
            "structure_fingerprint": structure_fingerprint,
            "n_atoms": 3,
            "total_energy_ev": -30.0,
            "forces_ev_angstrom": np.zeros((3, 3)),
            "stress_gpa": np.eye(3),
            "label_path": str(campaign_root / "qe-run-00/dft_label.json"),
            "label_sha256": "label-sha",
        },
    )
    records = load_labelled_records(
        [
            {
                "selection_id": "synthetic-selection",
                "snapshot_manifest": str(manifest_path),
                "snapshot_manifest_sha256": sha256_file(manifest_path),
                "dft_campaign_root": str(campaign_root),
            }
        ]
    )

    assert len(records) == 1
    assert records[0]["snapshot_id"] == "synthetic-00"
    assert records[0]["energy_per_atom_ev"] == pytest.approx(-10.0)
    assert records[0]["occupancy_seed"] == 2
    assert records[0]["stress_positive_tension_gpa"] == pytest.approx(np.eye(3))


def test_minimum_l2_atomref_alignment_changes_only_the_energy_reference():
    import torch
    from pymatgen.core import Lattice, Structure

    class FakeAtomRef(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = torch.nn.Linear(94, 1, bias=False)
            with torch.no_grad():
                self.fc.weight.zero_()

    class FakeModel:
        def __init__(self):
            self.composition_model = FakeAtomRef()

        def predict_structure(self, structure, task="e"):
            assert task == "e"
            fraction = np.zeros(94)
            for site in structure:
                fraction[site.specie.Z - 1] += 1 / len(structure)
            weight = (
                self.composition_model.fc.weight.detach().numpy().reshape(94)
            )
            return {"e": float(np.dot(fraction, weight)) + 0.75}

    structure = Structure(
        Lattice.cubic(8.0),
        ["Li", "Li", "O"],
        [[0, 0, 0], [0.25, 0.25, 0.25], [0.6, 0.6, 0.6]],
    )
    model = FakeModel()
    records = [
        {"structure": structure, "energy_per_atom_ev": -4.0},
        {"structure": structure.copy(), "energy_per_atom_ev": -3.0},
    ]
    report = align_atomref_minimum_l2(model, records)
    aligned = [model.predict_structure(row["structure"])["e"] for row in records]

    assert np.mean(aligned) == pytest.approx(-3.5, abs=2e-5)
    assert report["post_alignment_mean_residual_ev_atom"] == pytest.approx(
        0.0, abs=2e-5
    )
    assert all(
        parameter.requires_grad is False
        for parameter in model.composition_model.parameters()
    )


def test_transfer_scope_freezes_atomref_and_pretrained_feature_layers():
    from chgnet.model import CHGNet

    model = CHGNet.load(verbose=False, use_device="cpu")
    scope = freeze_transfer_layers(model)

    assert scope["n_trainable_parameters"] > 0
    assert scope["n_frozen_parameters"] > scope["n_trainable_parameters"]
    assert not any(
        name.startswith("composition_model")
        for name in scope["trainable_parameter_names"]
    )
    assert any(
        name.startswith("composition_model")
        for name in scope["frozen_parameter_names"]
    )
    assert any(
        name.startswith("atom_conv_layers.3")
        for name in scope["trainable_parameter_names"]
    )


def test_repository_contingency_protocol_locks_disjoint_templates_and_sources():
    protocol, _ = validate_finetune_protocol(
        ROOT / "analysis/protocols/llzto_chgnet_finetune_contingency_v1.json"
    )
    expansion = protocol["expansion_phase"]
    heldout = protocol["fresh_publication_test"]
    training_selection = json.loads(
        (ROOT / expansion["snapshot_selection_protocol"]).read_text(encoding="utf-8")
    )
    heldout_selection = json.loads(
        (ROOT / heldout["snapshot_selection_protocol"]).read_text(encoding="utf-8")
    )

    assert training_selection["expected_snapshot_count"] == 50
    assert heldout_selection["expected_snapshot_count"] == 30
    assert (
        training_selection["trajectory_matrices"][0]["trajectory_template"]
        != heldout_selection["trajectory_matrices"][0]["trajectory_template"]
    )
    assert protocol["final_training_phase"]["expected_records"] == 62
    assert "30" in protocol["trigger"]["hard_rule"]


def test_finetune_sampling_templates_require_derived_model_hashes():
    for filename in (
        "llzto_finetune_training_sampling_template_v1.json",
        "llzto_finetune_heldout_sampling_template_v1.json",
    ):
        campaign = load_campaign(ROOT / "protocols" / filename)
        assert len(campaign.runs) == 5
        assert all(
            run.config.expected_model_state_dict_sha256 is None
            for run in campaign.runs
        )
        assert all(run.enabled is False for run in campaign.runs)


def test_derived_campaign_locks_model_artifact_and_custom_loader(tmp_path, monkeypatch):
    import io

    import torch
    from chgnet.model import CHGNet

    from matfactory.mlipmd import _model_metadata

    model = CHGNet.load(verbose=False, use_device="cpu")
    model_path = tmp_path / "model.pth.tar"
    torch.save({"model": model.as_dict()}, model_path)
    metadata = _model_metadata(model, "synthetic-finetuned")
    training_report = {
        "schema_version": "1.0",
        "report_kind": "chgnet-fine-tuning",
        "phase": "bootstrap_phase",
        "fresh_publication_heldout_labels_read": False,
        "model_artifact": {
            "path": str(model_path),
            "sha256": sha256_file(model_path),
            "state_dict_sha256": metadata["state_dict_sha256"],
        },
    }
    training_report["report_fingerprint"] = fingerprint(training_report)
    training_report_path = tmp_path / "training-report.json"
    _write_json(training_report_path, training_report)
    template = json.loads(
        (
            ROOT / "protocols/llzto_finetune_training_sampling_template_v1.json"
        ).read_text(encoding="utf-8")
    )
    template["root_dir"] = str(tmp_path / "campaign-root")
    template_path = tmp_path / "campaign-template.json"
    _write_json(template_path, template)
    derived_path = tmp_path / "derived-campaign.json"
    summary = derive_model_campaign(
        template_path,
        training_report_path,
        out_path=derived_path,
        configured_model_name="LLZTO-synthetic-finetuned-v1",
    )
    selected_run = "finetune-train-occ00"
    validation = validate_custom_campaign(derived_path, {selected_run})

    assert summary["model_state_dict_sha256"] == metadata["state_dict_sha256"]
    assert validation["selected_run_ids"] == [selected_run]

    def fake_run_campaign(protocol_path, *, run_ids, quiet):
        loaded = CHGNet.load(verbose=False, use_device="cpu")
        observed = _model_metadata(loaded, "inside-custom-loader")
        return {
            "protocol_path": str(protocol_path),
            "run_ids": sorted(run_ids),
            "quiet": quiet,
            "state_dict_sha256": observed["state_dict_sha256"],
        }

    monkeypatch.setattr("matfactory.custom_campaign.run_campaign", fake_run_campaign)
    result = run_custom_campaign(derived_path, run_ids={selected_run}, quiet=True)
    assert result["state_dict_sha256"] == metadata["state_dict_sha256"]
    assert result["run_ids"] == [selected_run]

    campaign = load_campaign(derived_path)
    selected = next(run for run in campaign.runs if run.run_id == selected_run)
    protocol_fingerprint = "synthetic-complete-fingerprint"
    _write_json(
        selected.run_dir / "run_manifest.json",
        {
            "schema_version": "1.0",
            "protocol_fingerprint": protocol_fingerprint,
            "config": selected.config.as_dict(),
        },
    )
    _write_json(
        selected.run_dir / "result.json",
        {
            "schema_version": "2.1",
            "protocol_fingerprint": protocol_fingerprint,
            "status": "complete",
        },
    )
    gate_path = tmp_path / "bootstrap-model-gate.json"
    create_training_release_gate(
        training_report_path,
        gate_id="g2-finetune-bootstrap",
        out_path=gate_path,
    )
    monkeypatch.setattr(
        "matfactory.model_md_queue.acquire_gpu_lock", lambda _: io.BytesIO()
    )
    monkeypatch.setattr("matfactory.model_md_queue.release_gpu_lock", lambda _: None)
    monkeypatch.setattr("matfactory.model_md_queue.active_campaign_pids", lambda: [])
    monkeypatch.setattr("matfactory.model_md_queue.gpu_compute_pids", lambda: [])
    monkeypatch.setattr(
        "matfactory.model_md_queue.missing_structure_inputs", lambda _: []
    )
    queue_state = run_model_md_queue(
        derived_path,
        [selected_run],
        release_gate_path=gate_path,
        release_gate_id="g2-finetune-bootstrap",
        poll_seconds=1,
        state_path=tmp_path / "model-md-queue.json",
        gpu_lock_path=tmp_path / "gpu.lock",
    )
    assert queue_state["status"] == "complete"
    assert queue_state["jobs"][selected_run]["status"] == "already_complete"


def test_training_release_gate_is_phase_specific_and_hash_verified(tmp_path):
    artifact_path = tmp_path / "bootstrap-model.bin"
    artifact_path.write_bytes(b"immutable-model-artifact")
    report = {
        "schema_version": "1.0",
        "report_kind": "chgnet-fine-tuning",
        "phase": "bootstrap_phase",
        "fresh_publication_heldout_labels_read": False,
        "model_artifact": {
            "path": str(artifact_path),
            "sha256": sha256_file(artifact_path),
            "state_dict_sha256": "a" * 64,
        },
    }
    report["report_fingerprint"] = fingerprint(report)
    report_path = tmp_path / "bootstrap-report.json"
    _write_json(report_path, report)
    gate_path = tmp_path / "bootstrap-gate.json"

    gate = create_training_release_gate(
        report_path,
        gate_id="g2-finetune-bootstrap",
        out_path=gate_path,
    )
    assert gate["status"] == "pass"
    assert gate["model_state_dict_sha256"] == "a" * 64
    with pytest.raises(RuntimeError, match="cannot release"):
        create_training_release_gate(
            report_path,
            gate_id="g2-finetune-final-model",
            out_path=tmp_path / "wrong-gate.json",
        )


def test_finetuned_domain_keeps_thresholds_and_custom_prediction_identity(tmp_path):
    import torch
    from ase import Atoms
    from ase.io import read, write
    from chgnet.model import CHGNet

    from matfactory.mlipmd import _model_metadata

    model = CHGNet.load(verbose=False, use_device="cpu")
    model_path = tmp_path / "final-model.pth.tar"
    torch.save({"model": model.as_dict()}, model_path)
    metadata = _model_metadata(model, "final-finetuned")
    training_report = {
        "schema_version": "1.0",
        "report_kind": "chgnet-fine-tuning",
        "phase": "final_training_phase",
        "fresh_publication_heldout_labels_read": False,
        "model_artifact": {
            "path": str(model_path),
            "sha256": sha256_file(model_path),
            "state_dict_sha256": metadata["state_dict_sha256"],
        },
    }
    training_report["report_fingerprint"] = fingerprint(training_report)
    training_path = tmp_path / "final-training-report.json"
    _write_json(training_path, training_report)
    derived_path = tmp_path / "derived-domain.json"
    derive_finetuned_domain_protocol(
        ROOT / "analysis/protocols/llzto_chgnet_domain_v1.json",
        training_path,
        ROOT / "dft/protocols/llzto_finetune_fresh_heldout_snapshots_v1.json",
        out_path=derived_path,
    )
    base = json.loads(
        (ROOT / "analysis/protocols/llzto_chgnet_domain_v1.json").read_text()
    )
    derived = json.loads(derived_path.read_text())
    assert derived["aggregate_limits"] == base["aggregate_limits"]
    assert derived["robustness_limits"] == base["robustness_limits"]
    assert derived["model"]["expected_state_dict_sha256"] == metadata[
        "state_dict_sha256"
    ]

    atoms = Atoms(
        symbols=["Li", "Li", "O"],
        scaled_positions=[[0, 0, 0], [0.25, 0.25, 0.25], [0.6, 0.6, 0.6]],
        cell=np.eye(3) * 7.0,
        pbc=True,
    )
    snapshot_path = tmp_path / "heldout.extxyz"
    write(snapshot_path, atoms, format="extxyz")
    stored_atoms = read(snapshot_path, index=0)
    snapshot = {
        "snapshot_id": "synthetic-heldout-00",
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": sha256_file(snapshot_path),
        "structure_fingerprint": atoms_fingerprint(stored_atoms),
        "n_atoms": len(stored_atoms),
        "temperature_k": 800,
        "metadata": {"occupancy_seed": 0},
    }
    manifest = {
        "schema_version": "1.0",
        "selection_id": "synthetic-finetuned-heldout",
        "n_snapshots": 1,
        "snapshots": [snapshot],
    }
    manifest["snapshot_set_fingerprint"] = fingerprint(manifest)
    manifest_path = tmp_path / "heldout-manifest.json"
    _write_json(manifest_path, manifest)
    derived["sets"] = {
        "synthetic-set": {
            "selection_id": "synthetic-finetuned-heldout",
            "expected_snapshots": 1,
            "required_temperature_strata_k": [800],
            "required_occupancy_seeds": [0],
            "publication_claim_gate": True,
        }
    }
    derived["release_requirements"]["required_domain_sets"] = ["synthetic-set"]
    _write_json(derived_path, derived)
    prediction = predict_snapshot_set_custom(
        manifest_path,
        derived_path,
        model_path,
        set_id="synthetic-set",
        out_dir=tmp_path / "predictions",
        device="cpu",
    )
    label = json.loads(
        (tmp_path / "predictions/labels/synthetic-heldout-00.json").read_text()
    )
    assert prediction["model_state_dict_sha256"] == metadata["state_dict_sha256"]
    assert label["model_artifact_sha256"] == sha256_file(model_path)

    domain_report = {
        "schema_version": "1.0",
        "report_kind": "chgnet-dft-domain",
        "set_id": "fine-tuned-publication-heldout",
        "analysis_protocol_sha256": sha256_file(derived_path),
        "domain_gate_pass": True,
        "publication_claim_gate": True,
    }
    domain_report["report_fingerprint"] = fingerprint(domain_report)
    domain_path = tmp_path / "domain-report.json"
    _write_json(domain_path, domain_report)
    numerical = {}
    for stage in ("cutoff", "kpoint", "scf"):
        path = tmp_path / f"{stage}.json"
        _write_json(path, {"numerically_converged": True})
        numerical[stage] = path
    gate = create_finetuned_g2_release_gate(
        derived_path,
        domain_path,
        training_path,
        numerical_reports=numerical,
        gate_id="g2-finetuned-potential-domain",
        out_path=tmp_path / "finetuned-g2.json",
    )
    assert gate["status"] == "pass"
    assert gate["universal_g2_token_created"] is False


def test_contingency_queue_closes_without_training_after_universal_pass(tmp_path):
    protocol = json.loads(
        (
            ROOT
            / "analysis/protocols/llzto_chgnet_finetune_contingency_v1.json"
        ).read_text(encoding="utf-8")
    )
    universal_state_path = tmp_path / "universal-domain-state.json"
    _write_json(universal_state_path, {"status": "complete"})
    protocol["trigger"]["universal_domain_state"] = str(universal_state_path)
    protocol_path = tmp_path / "contingency.json"
    _write_json(protocol_path, protocol)

    state = run_finetune_contingency_queue(
        protocol_path,
        state_path=tmp_path / "contingency-state.json",
        gpu_lock_path=tmp_path / "gpu.lock",
    )
    assert state["status"] == "complete"
    assert state["disposition"] == "not_triggered_universal_domain_pass"
    assert not (tmp_path / "models").exists()


def test_finetune_watchdog_locks_the_conditional_supervisor_protocol():
    protocol_path = (
        ROOT / "analysis/protocols/llzto_chgnet_finetune_contingency_v1.json"
    )
    watchdog = json.loads(
        (
            ROOT / "analysis/protocols/llzto_finetune_watchdog_v1.json"
        ).read_text(encoding="utf-8")
    )
    managed = watchdog["managed"]

    assert len(managed) == 1
    assert managed[0]["marker"] == "matfactory.finetune_queue"
    assert managed[0]["policy"] == "restart-waiting-only"
    assert managed[0]["expected_protocol_sha256"] == sha256_file(protocol_path)
