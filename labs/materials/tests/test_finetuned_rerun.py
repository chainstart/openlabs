from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.campaign import load_campaign  # noqa: E402
from matfactory.finetuned_rerun import (  # noqa: E402
    build_relaxed_matched_supercell,
    derive_finetuned_downstream_protocols,
    derive_transport_campaign,
    run_finetuned_rerun_supervisor,
    validate_rerun_protocol,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402
from matfactory.structures import structure_fingerprint  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _runtime_protocol(tmp_path: Path) -> Path:
    source = ROOT / "analysis/protocols/llzto_finetuned_rerun_supervisor_v1.json"
    protocol = json.loads(source.read_text(encoding="utf-8"))
    for name, specification in protocol["campaigns"].items():
        specification["derived_protocol"] = str(tmp_path / f"{name}.json")
        specification["root_dir"] = str(tmp_path / f"campaign-{name}")
        specification["queue_state"] = str(tmp_path / f"queue-{name}.json")
    protocol["campaigns"]["velocity"]["string_replacements"] = {
        "runs/campaigns/llzto_q1_v1": str(tmp_path / "campaign-formal")
    }
    protocol["campaigns"]["ensemble_nve"]["string_replacements"] = {
        "runs/campaigns/llzto_q1_v1": str(tmp_path / "campaign-formal")
    }
    protocol["campaigns"]["size"]["base_config_overrides"][
        "structure_file"
    ] = str(tmp_path / "matched.structure.json")
    protocol["downstream"]["hierarchical_derived_protocol"] = str(
        tmp_path / "hierarchical.json"
    )
    protocol["downstream"]["mechanism_association_derived_protocol"] = str(
        tmp_path / "mechanism-association.json"
    )
    protocol["downstream"]["mechanism_root"] = str(tmp_path / "mechanisms")
    protocol["downstream"]["mechanism_queue_state"] = str(
        tmp_path / "mechanism-queue.json"
    )
    protocol["matched_supercell"]["output_prefix"] = str(tmp_path / "matched")
    destination = tmp_path / "rerun-protocol.json"
    _write_json(destination, protocol)
    return destination


def _final_training_report(tmp_path: Path) -> tuple[Path, str]:
    import torch
    from chgnet.model import CHGNet

    from matfactory.mlipmd import _model_metadata

    model = CHGNet.load(verbose=False, use_device="cpu")
    model_path = tmp_path / "model.pth.tar"
    torch.save({"model": model.as_dict()}, model_path)
    state_sha = _model_metadata(model, "synthetic-finetuned")["state_dict_sha256"]
    report = {
        "schema_version": "1.0",
        "report_kind": "chgnet-fine-tuning",
        "phase": "final_training_phase",
        "fresh_publication_heldout_labels_read": False,
        "model_artifact": {
            "path": str(model_path),
            "sha256": sha256_file(model_path),
            "state_dict_sha256": state_sha,
        },
    }
    report["report_fingerprint"] = fingerprint(report)
    report_path = tmp_path / "training-report.json"
    _write_json(report_path, report)
    return report_path, state_sha


def test_repository_rerun_protocol_locks_all_model_consistent_controls():
    protocol, source = validate_rerun_protocol(
        ROOT / "analysis/protocols/llzto_finetuned_rerun_supervisor_v1.json"
    )

    assert source.is_file()
    assert list(protocol["campaigns"]) == [
        "formal",
        "fixed_volume",
        "velocity",
        "size",
        "ensemble_nve",
    ]
    assert len(protocol["campaigns"]["formal"]["run_ids"]) == 8
    assert protocol["campaigns"]["formal"]["run_ids"][:2] == [
        "numerics-dt1fs-800k-nve",
        "numerics-dt2fs-800k-nve",
    ]
    assert len(protocol["campaigns"]["velocity"]["run_ids"]) == 10
    assert protocol["campaigns"]["size"]["base_config_overrides"] == {
        "structure_file": (
            "runs/structures/llzto_finetuned_occ00_conventional_v1.structure.json"
        ),
        "structure_id": (
            "llzto-finetuned-occ00-relaxed-exact-twofold-supercell"
        ),
        "relax_structure": False,
        "relax_cell": False,
    }
    assert protocol["matched_supercell"]["matrix"] == [
        [1, 1, 0],
        [1, 0, 1],
        [0, -1, -1],
    ]
    watchdog = json.loads(
        (
            ROOT
            / "analysis/protocols/llzto_finetuned_rerun_watchdog_v1.json"
        ).read_text()
    )
    assert watchdog["managed"][0]["expected_protocol_sha256"] == sha256_file(
        source
    )
    assert watchdog["managed"][0]["policy"] == "restart-waiting-only"


def test_transport_derivation_rebinds_one_artifact_and_every_reference(
    tmp_path,
):
    protocol_path = _runtime_protocol(tmp_path)
    training_report, state_sha = _final_training_report(tmp_path)

    summaries = {
        name: derive_transport_campaign(
            protocol_path, name, training_report_path=training_report
        )
        for name in ("formal", "fixed_volume", "velocity", "size", "ensemble_nve")
    }

    for name, summary in summaries.items():
        campaign = load_campaign(summary["path"])
        assert summary["model_state_dict_sha256"] == state_sha
        assert all(run.config.expected_model_state_dict_sha256 == state_sha for run in campaign.runs)
        assert all(run.config.model_name == "LLZTO-CHGNet-finetuned-v1" for run in campaign.runs)
        payload = json.loads(Path(summary["path"]).read_text(encoding="utf-8"))
        assert payload["derivation"]["campaign_role"] == name
        assert payload["derived_model_artifact"]["state_dict_sha256"] == state_sha

    velocity = json.loads(Path(summaries["velocity"]["path"]).read_text())
    ensemble = json.loads(Path(summaries["ensemble_nve"]["path"]).read_text())
    assert "runs/campaigns/llzto_q1_v1" not in json.dumps(velocity)
    assert "runs/campaigns/llzto_q1_v1" not in json.dumps(ensemble)
    assert str(tmp_path / "campaign-formal") in json.dumps(velocity)
    assert str(tmp_path / "campaign-formal") in json.dumps(ensemble)

    derived_analysis = derive_finetuned_downstream_protocols(protocol_path)
    hierarchical = json.loads(
        Path(derived_analysis["hierarchical"]["path"]).read_text()
    )
    association = json.loads(
        Path(derived_analysis["mechanism_association"]["path"]).read_text()
    )
    assert hierarchical["formal_campaign_root"] == str(
        tmp_path / "campaign-formal"
    )
    assert hierarchical["sensitivity_roles"]["velocity_design"][
        "supplemental_campaign_root"
    ] == str(tmp_path / "campaign-velocity")
    assert association["formal_campaign"]["protocol_sha256"] == sha256_file(
        summaries["formal"]["path"]
    )
    assert association["mechanism_inputs"]["analysis_root"] == str(
        tmp_path / "mechanisms"
    )


def test_relaxed_supercell_is_exactly_doubled_and_hash_linked(tmp_path):
    from pymatgen.core import Lattice, Structure

    parent = Structure(
        Lattice.cubic(8.0),
        ["Li", "Li", "O"],
        [[0, 0, 0], [0.25, 0.25, 0.25], [0.6, 0.6, 0.6]],
    )
    parent_path = tmp_path / "relaxed.structure.json"
    _write_json(parent_path, parent.as_dict())
    state_sha = "a" * 64
    manifest = {
        "schema_version": "2.1",
        "model": {"state_dict_sha256": state_sha},
        "config": {"expected_model_state_dict_sha256": state_sha},
        "relaxation": {
            "converged": True,
            "output_structure_sha256": sha256_file(parent_path),
            "relaxation_protocol": {"model_state_dict_sha256": state_sha},
        },
    }
    manifest_path = tmp_path / "run_manifest.json"
    _write_json(manifest_path, manifest)

    report = build_relaxed_matched_supercell(
        parent_path,
        manifest_path,
        tmp_path / "matched",
        matrix=[[1, 1, 0], [1, 0, 1], [0, -1, -1]],
        expected_model_state_dict_sha256=state_sha,
    )
    child = Structure.from_dict(json.loads(Path(report["structure_path"]).read_text()))
    provenance = json.loads(Path(report["provenance_path"]).read_text())

    assert len(child) == 2 * len(parent)
    assert child.volume == pytest.approx(2 * parent.volume)
    assert provenance["parent"]["structure_sha256"] == structure_fingerprint(parent)
    assert provenance["child"]["structure_sha256"] == structure_fingerprint(child)
    assert provenance["outputs"]["structure_json_sha256"] == sha256_file(
        report["structure_path"]
    )

    assert build_relaxed_matched_supercell(
        parent_path,
        manifest_path,
        tmp_path / "matched",
        matrix=[[1, 1, 0], [1, 0, 1], [0, -1, -1]],
        expected_model_state_dict_sha256=state_sha,
    ) == report


def test_rerun_supervisor_is_inert_after_universal_domain_pass(tmp_path):
    protocol_path = _runtime_protocol(tmp_path)
    protocol = json.loads(protocol_path.read_text())
    contingency_state = tmp_path / "contingency-state.json"
    _write_json(
        contingency_state,
        {
            "schema_version": "1.0",
            "status": "complete",
            "disposition": "not_triggered_universal_domain_pass",
        },
    )
    protocol["trigger"]["contingency_state"] = str(contingency_state)
    _write_json(protocol_path, protocol)

    result = run_finetuned_rerun_supervisor(
        protocol_path,
        state_path=tmp_path / "rerun-state.json",
        gpu_lock_path=tmp_path / "gpu.lock",
    )

    assert result["status"] == "complete"
    assert result["disposition"] == "not_triggered_universal_domain_pass"
    assert result["stages"] == {}
