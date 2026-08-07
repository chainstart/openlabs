"""Conditional full transport rerun for a released fine-tuned LLZTO model."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from .campaign import load_campaign
from .custom_campaign import validate_custom_campaign
from .matched_supercell import validate_supercell_matrix
from .mechanism_queue import run_queue as run_mechanism_queue
from .model_md_queue import run_model_md_queue
from .provenance import atomic_write_json, fingerprint, sha256_file
from .structures import structure_fingerprint


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


def _write_or_verify(path: Path, payload: dict[str, Any], *, label: str) -> None:
    if path.exists():
        if _read_json(path) != payload:
            raise RuntimeError(f"existing {label} differs: {path}")
        return
    atomic_write_json(path, payload)


def validate_rerun_protocol(path: Path | str) -> tuple[dict[str, Any], Path]:
    """Validate every static preregistration input of the rerun branch."""
    source = Path(path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("fine-tuned rerun protocol schema_version must be '1.0'")
    if protocol.get("protocol_id") != "llzto-finetuned-rerun-supervisor-v1":
        raise ValueError("unexpected fine-tuned rerun protocol id")
    trigger = protocol["trigger"]
    declared = [
        (
            trigger["contingency_protocol"],
            trigger["contingency_protocol_sha256"],
        ),
        (
            protocol["downstream"]["hierarchical_source_protocol"],
            protocol["downstream"]["hierarchical_source_protocol_sha256"],
        ),
        (
            protocol["downstream"]["mechanism_association_source_protocol"],
            protocol["downstream"][
                "mechanism_association_source_protocol_sha256"
            ],
        ),
    ]
    declared.extend(
        (record["source_protocol"], record["source_protocol_sha256"])
        for record in protocol["campaigns"].values()
    )
    for value, expected in declared:
        candidate = _repo_path(value)
        if sha256_file(candidate) != expected:
            raise RuntimeError(f"fine-tuned rerun declared hash mismatch: {candidate}")

    campaign_names = list(protocol["campaigns"])
    if campaign_names != [
        "formal",
        "fixed_volume",
        "velocity",
        "size",
        "ensemble_nve",
    ]:
        raise ValueError("fine-tuned rerun campaign order changed")
    destinations: set[str] = set()
    for name, specification in protocol["campaigns"].items():
        run_ids = specification.get("run_ids")
        if not isinstance(run_ids, list) or not run_ids or len(run_ids) != len(
            set(run_ids)
        ):
            raise ValueError(f"invalid rerun list for {name}")
        for key in ("derived_protocol", "root_dir", "queue_state"):
            value = str(specification[key])
            if value in destinations:
                raise ValueError(f"duplicate fine-tuned rerun destination: {value}")
            destinations.add(value)
        source_campaign = load_campaign(_repo_path(specification["source_protocol"]))
        source_ids = {row.run_id for row in source_campaign.runs}
        missing = set(run_ids) - source_ids
        if missing:
            raise ValueError(
                f"unknown source run(s) for {name}: " + ", ".join(sorted(missing))
            )
    matrix, determinant = validate_supercell_matrix(
        protocol["matched_supercell"]["matrix"]
    )
    if determinant != 2:
        raise ValueError("fine-tuned matched supercell must be exactly twofold")
    protocol["matched_supercell"]["matrix"] = matrix
    return protocol, source


def _model_identity(
    training_report_path: Path | str, *, configured_name: str
) -> dict[str, Any]:
    from chgnet.model import CHGNet

    from .mlipmd import _model_metadata

    report_path = Path(training_report_path).resolve()
    report = _read_json(report_path)
    _verify_fingerprint(report, "report_fingerprint", "fine-tuned training report")
    if (
        report.get("report_kind") != "chgnet-fine-tuning"
        or report.get("phase") != "final_training_phase"
        or report.get("fresh_publication_heldout_labels_read") is not False
    ):
        raise RuntimeError("rerun requires the label-blind final fine-tuning report")
    artifact = report.get("model_artifact", {})
    artifact_path = Path(artifact["path"]).resolve()
    if sha256_file(artifact_path) != artifact.get("sha256"):
        raise RuntimeError("fine-tuned rerun model artifact changed")
    model = CHGNet.from_file(str(artifact_path))
    observed = _model_metadata(model, configured_name)
    if observed["state_dict_sha256"] != artifact.get("state_dict_sha256"):
        raise RuntimeError("fine-tuned rerun model state dictionary changed")
    return {
        "report": report,
        "report_path": report_path,
        "artifact": artifact,
        "artifact_path": artifact_path,
        "metadata": observed,
    }


def _replace_strings(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _replace_strings(item, replacements) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_strings(item, replacements) for item in value]
    if isinstance(value, str):
        result = value
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result
    return value


def derive_transport_campaign(
    rerun_protocol_path: Path | str,
    campaign_name: str,
    *,
    training_report_path: Path | str | None = None,
) -> dict[str, Any]:
    """Derive one immutable campaign by changing only branch/model identity."""
    protocol, supervisor_path = validate_rerun_protocol(rerun_protocol_path)
    if campaign_name not in protocol["campaigns"]:
        raise ValueError(f"unknown fine-tuned rerun campaign {campaign_name!r}")
    specification = protocol["campaigns"][campaign_name]
    report_path = (
        _repo_path(protocol["trigger"]["final_training_report"])
        if training_report_path is None
        else Path(training_report_path).resolve()
    )
    identity = _model_identity(
        report_path, configured_name=protocol["model"]["configured_name"]
    )
    source_path = _repo_path(specification["source_protocol"])
    source = _read_json(source_path)
    if sha256_file(source_path) != specification["source_protocol_sha256"]:
        raise RuntimeError("fine-tuned rerun source campaign changed")
    base = source.get("base_config", {})
    if base.get("expected_model_state_dict_sha256") != protocol["model"][
        "universal_state_dict_sha256"
    ]:
        raise RuntimeError("rerun source does not carry the frozen universal model")

    replacements = {
        str(key): str(value)
        for key, value in specification.get("string_replacements", {}).items()
    }
    original_text = json.dumps(source, sort_keys=True)
    for old in replacements:
        if old not in original_text:
            raise RuntimeError(f"rerun replacement source is absent: {old}")
    derived = _replace_strings(copy.deepcopy(source), replacements)
    derived["campaign_id"] = specification["campaign_id"]
    derived["root_dir"] = specification["root_dir"]
    derived["base_config"]["protocol_name"] = specification["protocol_name"]
    derived["base_config"]["model_name"] = protocol["model"]["configured_name"]
    derived["base_config"]["expected_model_state_dict_sha256"] = identity[
        "artifact"
    ]["state_dict_sha256"]
    derived["base_config"].update(specification.get("base_config_overrides", {}))
    derived["derived_model_artifact"] = {
        "path": str(identity["artifact_path"]),
        "sha256": sha256_file(identity["artifact_path"]),
        "state_dict_sha256": identity["artifact"]["state_dict_sha256"],
        "training_report_path": str(identity["report_path"]),
        "training_report_sha256": sha256_file(identity["report_path"]),
        "training_report_fingerprint": identity["report"]["report_fingerprint"],
    }
    derived["derivation"] = {
        "kind": "fine-tuned-full-transport-rerun",
        "campaign_role": campaign_name,
        "supervisor_protocol_path": str(supervisor_path),
        "supervisor_protocol_sha256": sha256_file(supervisor_path),
        "source_protocol_path": str(source_path),
        "source_protocol_sha256": sha256_file(source_path),
        "specification_fingerprint": fingerprint(specification),
        "allowed_changes": [
            "campaign_id",
            "root_dir",
            "base_config.protocol_name",
            "base_config.model_name",
            "base_config.expected_model_state_dict_sha256",
            "declared string replacements",
            "declared base-config overrides",
            "derived_model_artifact",
            "derivation",
            "derivation_fingerprint",
        ],
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    derived["derivation_fingerprint"] = fingerprint(derived)
    destination = _repo_path(specification["derived_protocol"])
    if destination.exists():
        if _read_json(destination) != derived:
            raise RuntimeError(f"existing derived campaign differs: {destination}")
    else:
        atomic_write_json(destination, derived)

    campaign = load_campaign(destination)
    if (
        campaign.campaign_id != specification["campaign_id"]
        or campaign.root_dir != _repo_path(specification["root_dir"])
    ):
        raise RuntimeError("derived fine-tuned campaign identity mismatch")
    validation = validate_custom_campaign(
        destination, set(map(str, specification["run_ids"]))
    )
    return {
        "campaign_name": campaign_name,
        "path": str(destination),
        "sha256": sha256_file(destination),
        "campaign_id": campaign.campaign_id,
        "root_dir": str(campaign.root_dir),
        "run_ids": list(specification["run_ids"]),
        "model_state_dict_sha256": validation["model_state_dict_sha256"],
        "model_artifact_sha256": validation["artifact_sha256"],
        "derivation_fingerprint": derived["derivation_fingerprint"],
    }


def build_relaxed_matched_supercell(
    parent_structure_path: Path | str,
    parent_run_manifest_path: Path | str,
    output_prefix: Path | str,
    *,
    matrix: Any,
    expected_model_state_dict_sha256: str,
) -> dict[str, Any]:
    """Replicate the exact fine-tuned relaxed parent without another relaxation."""
    from pymatgen.core import Structure

    parent_path = Path(parent_structure_path).resolve()
    manifest_path = Path(parent_run_manifest_path).resolve()
    normalized, determinant = validate_supercell_matrix(matrix)
    if determinant != 2:
        raise ValueError("fine-tuned size control must be a twofold replication")
    manifest = _read_json(manifest_path)
    checks = {
        "manifest_model": manifest.get("model", {}).get("state_dict_sha256")
        == expected_model_state_dict_sha256,
        "configured_model": manifest.get("config", {}).get(
            "expected_model_state_dict_sha256"
        )
        == expected_model_state_dict_sha256,
        "relaxation_model": manifest.get("relaxation", {})
        .get("relaxation_protocol", {})
        .get("model_state_dict_sha256")
        == expected_model_state_dict_sha256,
        "relaxation_converged": manifest.get("relaxation", {}).get("converged")
        is True,
        "relaxed_structure_hash": manifest.get("relaxation", {}).get(
            "output_structure_sha256"
        )
        == sha256_file(parent_path),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            "fine-tuned matched-supercell parent provenance failed: "
            + ", ".join(failed)
        )
    parent = Structure.from_dict(_read_json(parent_path))
    parent_fingerprint = structure_fingerprint(parent)
    child = parent.copy()
    child.make_supercell(normalized)
    if len(child) != determinant * len(parent):
        raise AssertionError("fine-tuned supercell site count is not exactly doubled")
    if structure_fingerprint(parent) != parent_fingerprint:
        raise AssertionError("fine-tuned supercell construction mutated its parent")

    prefix = Path(output_prefix).resolve()
    structure_path = Path(f"{prefix}.structure.json")
    provenance_path = Path(f"{prefix}.provenance.json")
    structure_payload = child.as_dict()
    if structure_path.exists():
        existing_child = Structure.from_dict(_read_json(structure_path))
        if structure_fingerprint(existing_child) != structure_fingerprint(child):
            raise RuntimeError(f"existing fine-tuned supercell differs: {structure_path}")
    else:
        atomic_write_json(structure_path, structure_payload)
    provenance: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_kind": "exact-relaxed-periodic-supercell",
        "claim_role": "fine-tuned-model matched finite-size sensitivity control",
        "parent": {
            "path": str(parent_path),
            "sha256": sha256_file(parent_path),
            "run_manifest_path": str(manifest_path),
            "run_manifest_sha256": sha256_file(manifest_path),
            "n_sites": len(parent),
            "volume_angstrom3": float(parent.volume),
            "structure_sha256": parent_fingerprint,
            "model_state_dict_sha256": expected_model_state_dict_sha256,
        },
        "supercell_matrix": normalized,
        "size_multiplier": determinant,
        "child": {
            "n_sites": len(child),
            "volume_angstrom3": float(child.volume),
            "structure_sha256": structure_fingerprint(child),
        },
        "construction_rule": (
            "Load the exact converged relaxed structure from the fine-tuned "
            "occupancy-0 formal run, then apply the frozen determinant-two "
            "integer lattice transform. No site is reordered or resampled and "
            "the child receives no additional structural or cell relaxation."
        ),
        "outputs": {
            "structure_json_path": str(structure_path),
            "structure_json_sha256": sha256_file(structure_path),
        },
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    _write_or_verify(provenance_path, provenance, label="supercell provenance")
    return {
        "structure_path": str(structure_path),
        "structure_sha256": sha256_file(structure_path),
        "provenance_path": str(provenance_path),
        "provenance_sha256": sha256_file(provenance_path),
        "parent_structure_sha256": parent_fingerprint,
        "child_structure_sha256": structure_fingerprint(child),
        "size_multiplier": determinant,
    }


def derive_finetuned_downstream_protocols(
    rerun_protocol_path: Path | str,
) -> dict[str, dict[str, Any]]:
    """Rebind frozen analysis designs to the fine-tuned campaign branch."""
    protocol, supervisor_path = validate_rerun_protocol(rerun_protocol_path)
    downstream = protocol["downstream"]
    campaigns = protocol["campaigns"]

    campaign_paths = {
        name: _repo_path(specification["derived_protocol"])
        for name, specification in campaigns.items()
    }
    for path in campaign_paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)

    hierarchical_source = _repo_path(downstream["hierarchical_source_protocol"])
    hierarchical = copy.deepcopy(_read_json(hierarchical_source))
    formal = campaigns["formal"]
    velocity = campaigns["velocity"]
    size = campaigns["size"]
    fixed = campaigns["fixed_volume"]
    hierarchical["protocol_id"] = "llzto-hierarchical-transport-finetuned-v1"
    hierarchical["formal_campaign_protocol_path"] = formal["derived_protocol"]
    hierarchical["formal_campaign_root"] = formal["root_dir"]
    roles = hierarchical["sensitivity_roles"]
    velocity_role = roles["velocity_design"]
    velocity_role["reference_campaign_root"] = formal["root_dir"]
    velocity_role["reference_protocol_path"] = formal["derived_protocol"]
    velocity_role["supplemental_campaign_root"] = velocity["root_dir"]
    velocity_role["supplemental_protocol_path"] = velocity["derived_protocol"]
    roles["finite_size_campaign_root"] = size["root_dir"]
    roles["finite_size_protocol_path"] = size["derived_protocol"]
    roles["fixed_experimental_volume_campaign_root"] = fixed["root_dir"]
    roles["fixed_experimental_volume_protocol_path"] = fixed["derived_protocol"]
    hierarchical["branch_scope"] = {
        "model": protocol["model"]["configured_name"],
        "hard_rule": "Every transport input is from the fine-tuned branch; universal-model results are excluded and never pooled.",
    }
    hierarchical["derivation"] = {
        "source_path": str(hierarchical_source),
        "source_sha256": sha256_file(hierarchical_source),
        "supervisor_protocol_path": str(supervisor_path),
        "supervisor_protocol_sha256": sha256_file(supervisor_path),
        "campaign_protocols": {
            name: {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for name, path in sorted(campaign_paths.items())
        },
        "statistics_and_thresholds_unchanged": True,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    hierarchical["derivation_fingerprint"] = fingerprint(hierarchical)
    hierarchical_path = _repo_path(downstream["hierarchical_derived_protocol"])
    _write_or_verify(
        hierarchical_path, hierarchical, label="fine-tuned hierarchical protocol"
    )

    association_source = _repo_path(
        downstream["mechanism_association_source_protocol"]
    )
    association = copy.deepcopy(_read_json(association_source))
    association["protocol_id"] = (
        "llzto-mechanism-transport-association-finetuned-v1"
    )
    formal_section = association["formal_campaign"]
    formal_section["protocol_path"] = formal["derived_protocol"]
    formal_section["protocol_sha256"] = sha256_file(campaign_paths["formal"])
    formal_section["campaign_id"] = formal["campaign_id"]
    formal_section["campaign_root"] = formal["root_dir"]
    association["mechanism_inputs"]["analysis_root"] = downstream[
        "mechanism_root"
    ]
    association["branch_scope"] = {
        "model": protocol["model"]["configured_name"],
        "hard_rule": "Mechanism descriptors and transport responses both originate from the same fine-tuned trajectory bytes.",
    }
    association["derivation"] = {
        "source_path": str(association_source),
        "source_sha256": sha256_file(association_source),
        "supervisor_protocol_path": str(supervisor_path),
        "supervisor_protocol_sha256": sha256_file(supervisor_path),
        "formal_campaign_protocol_path": str(campaign_paths["formal"]),
        "formal_campaign_protocol_sha256": sha256_file(campaign_paths["formal"]),
        "model_and_path_only_derivation": True,
        "inferential_design_and_thresholds_unchanged": True,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    association["derivation_fingerprint"] = fingerprint(association)
    association_path = _repo_path(
        downstream["mechanism_association_derived_protocol"]
    )
    _write_or_verify(
        association_path,
        association,
        label="fine-tuned mechanism-association protocol",
    )
    return {
        "hierarchical": {
            "path": str(hierarchical_path),
            "sha256": sha256_file(hierarchical_path),
            "derivation_fingerprint": hierarchical["derivation_fingerprint"],
        },
        "mechanism_association": {
            "path": str(association_path),
            "sha256": sha256_file(association_path),
            "derivation_fingerprint": association["derivation_fingerprint"],
        },
    }


def _update(path: Path, state: dict[str, Any], status: str, **fields: Any) -> None:
    state["status"] = status
    state.update(fields)
    state["updated_unix_time"] = time.time()
    atomic_write_json(path, state)


def _queue_stage_record(state_path: Path) -> dict[str, Any]:
    queue = _read_json(state_path)
    if queue.get("status") != "complete":
        raise RuntimeError(f"fine-tuned rerun queue did not complete: {state_path}")
    return {
        "status": "complete",
        "path": str(state_path),
        "sha256": sha256_file(state_path),
        "jobs": len(queue.get("jobs", {})),
    }


def run_finetuned_rerun_supervisor(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
    gpu_lock_path: Path | str | None = None,
) -> dict[str, Any]:
    """Wait for the fallback decision, then run all model-consistent evidence."""
    protocol, source = validate_rerun_protocol(protocol_path)
    resources = protocol["resources"]
    poll_seconds = float(resources["poll_seconds"])
    if not 5 <= poll_seconds <= 60:
        raise ValueError("fine-tuned rerun poll_seconds must be between 5 and 60")
    output = Path(state_path).resolve()
    trigger = protocol["trigger"]
    trigger_state_path = _repo_path(trigger["contingency_state"])
    report_path = _repo_path(trigger["final_training_report"])
    release_path = _repo_path(trigger["release_gate"])
    gpu_lock = (
        _repo_path(resources["gpu_lock"])
        if gpu_lock_path is None
        else Path(gpu_lock_path).resolve()
    )
    locked_paths = [
        source,
        Path(__file__).resolve(),
        Path(__file__).with_name("campaign.py").resolve(),
        Path(__file__).with_name("custom_campaign.py").resolve(),
        Path(__file__).with_name("matched_supercell.py").resolve(),
        Path(__file__).with_name("mlipmd.py").resolve(),
        Path(__file__).with_name("model_md_queue.py").resolve(),
        Path(__file__).with_name("mechanism_queue.py").resolve(),
        Path(__file__).with_name("provenance.py").resolve(),
        Path(__file__).with_name("structures.py").resolve(),
        _repo_path(trigger["contingency_protocol"]),
        *[
            _repo_path(row["source_protocol"])
            for row in protocol["campaigns"].values()
        ],
        _repo_path(protocol["downstream"]["hierarchical_source_protocol"]),
        _repo_path(
            protocol["downstream"]["mechanism_association_source_protocol"]
        ),
    ]
    locked_files = [
        {"path": str(path), "sha256": sha256_file(path)} for path in locked_paths
    ]

    def verify_locks() -> None:
        for row in locked_files:
            if sha256_file(row["path"]) != row["sha256"]:
                raise RuntimeError(
                    f"fine-tuned rerun locked file changed: {row['path']}"
                )

    config = {
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "trigger_state_path": str(trigger_state_path),
        "gpu_lock_path": str(gpu_lock),
        "locked_files": locked_files,
    }
    queue_fingerprint = fingerprint(config)
    if output.is_file():
        state = _read_json(output)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"fine-tuned rerun configuration changed: {output}")
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": queue_fingerprint,
            "config": config,
            "created_unix_time": time.time(),
            "stages": {},
        }
        _update(output, state, "created")

    try:
        while True:
            verify_locks()
            if trigger_state_path.is_file():
                contingency = _read_json(trigger_state_path)
                if contingency.get("status") == "complete":
                    disposition = contingency.get("disposition")
                    if disposition == trigger["not_triggered_disposition"]:
                        _update(
                            output,
                            state,
                            "complete",
                            disposition="not_triggered_universal_domain_pass",
                            contingency_state_sha256=sha256_file(trigger_state_path),
                            waiting=None,
                        )
                        return state
                    if disposition == trigger["triggered_disposition"]:
                        break
                elif str(contingency.get("status", "")).startswith("blocked_"):
                    _update(
                        output,
                        state,
                        "blocked_finetuned_release_unavailable",
                        blocker={
                            "contingency_status": contingency.get("status"),
                            "path": str(trigger_state_path),
                            "sha256": sha256_file(trigger_state_path),
                        },
                    )
                    return state
                elif contingency.get("status") == "failed":
                    raise RuntimeError("fine-tuning contingency failed unexpectedly")
            _update(
                output,
                state,
                "waiting_for_finetune_contingency",
                waiting={
                    "path": str(trigger_state_path),
                    "checked_unix_time": time.time(),
                },
            )
            time.sleep(poll_seconds)

        identity = _model_identity(
            report_path, configured_name=protocol["model"]["configured_name"]
        )
        from .md_queue import verify_release_gate

        release = verify_release_gate(
            release_path, gate_id=trigger["release_gate_id"]
        )
        release_payload = _read_json(release_path)
        if release_payload.get("model_state_dict_sha256") != identity["artifact"].get(
            "state_dict_sha256"
        ):
            raise RuntimeError("fine-tuned rerun release belongs to another model")
        state["stages"]["release"] = {
            "status": "pass",
            "path": str(release_path),
            "sha256": sha256_file(release_path),
            "gate": release,
            "model_state_dict_sha256": identity["artifact"][
                "state_dict_sha256"
            ],
        }

        for campaign_name in ("formal", "fixed_volume"):
            verify_locks()
            specification = protocol["campaigns"][campaign_name]
            derived = derive_transport_campaign(
                source, campaign_name, training_report_path=report_path
            )
            queue_state = _repo_path(specification["queue_state"])
            _update(
                output,
                state,
                f"running_{campaign_name}_transport",
                current={
                    "campaign": campaign_name,
                    "protocol_path": derived["path"],
                    "queue_state": str(queue_state),
                },
                waiting=None,
            )
            run_model_md_queue(
                derived["path"],
                list(specification["run_ids"]),
                release_gate_path=release_path,
                release_gate_id=trigger["release_gate_id"],
                poll_seconds=poll_seconds,
                state_path=queue_state,
                gpu_lock_path=gpu_lock,
            )
            state["stages"][f"{campaign_name}_transport"] = {
                **_queue_stage_record(queue_state),
                "campaign_protocol_path": derived["path"],
                "campaign_protocol_sha256": derived["sha256"],
            }

        matched = protocol["matched_supercell"]
        supercell = build_relaxed_matched_supercell(
            _repo_path(matched["parent_structure"]),
            _repo_path(matched["parent_run_manifest"]),
            _repo_path(matched["output_prefix"]),
            matrix=matched["matrix"],
            expected_model_state_dict_sha256=identity["artifact"][
                "state_dict_sha256"
            ],
        )
        state["stages"]["matched_supercell"] = {
            "status": "complete",
            **supercell,
        }

        for campaign_name in ("velocity", "size", "ensemble_nve"):
            verify_locks()
            specification = protocol["campaigns"][campaign_name]
            derived = derive_transport_campaign(
                source, campaign_name, training_report_path=report_path
            )
            queue_state = _repo_path(specification["queue_state"])
            _update(
                output,
                state,
                f"running_{campaign_name}_transport",
                current={
                    "campaign": campaign_name,
                    "protocol_path": derived["path"],
                    "queue_state": str(queue_state),
                },
                waiting=None,
            )
            run_model_md_queue(
                derived["path"],
                list(specification["run_ids"]),
                release_gate_path=release_path,
                release_gate_id=trigger["release_gate_id"],
                poll_seconds=poll_seconds,
                state_path=queue_state,
                gpu_lock_path=gpu_lock,
            )
            state["stages"][f"{campaign_name}_transport"] = {
                **_queue_stage_record(queue_state),
                "campaign_protocol_path": derived["path"],
                "campaign_protocol_sha256": derived["sha256"],
            }

        derived_analysis = derive_finetuned_downstream_protocols(source)
        state["stages"]["derived_analysis_protocols"] = {
            "status": "complete",
            **derived_analysis,
        }
        downstream = protocol["downstream"]
        mechanism_state = _repo_path(downstream["mechanism_queue_state"])
        _update(
            output,
            state,
            "running_finetuned_mechanisms",
            current={"queue_state": str(mechanism_state)},
            waiting=None,
        )
        run_mechanism_queue(
            derived_analysis["mechanism_association"]["path"],
            release_gate_path=release_path,
            release_gate_id=trigger["release_gate_id"],
            state_path=mechanism_state,
            cpu_lock_path=_repo_path(resources["cpu_lock"]),
            poll_seconds=poll_seconds,
            minimum_available_memory_gib=float(
                resources["minimum_available_memory_gib"]
            ),
        )
        state["stages"]["formal_mechanisms"] = _queue_stage_record(
            mechanism_state
        )
        _update(
            output,
            state,
            "complete",
            disposition=(
                "fine_tuned_transport_and_mechanisms_complete_requires_"
                "versioned_final_analysis"
            ),
            current=None,
            waiting=None,
            final_analysis_required=bool(downstream["final_analysis_required"]),
        )
        return state
    except BaseException as exc:
        _update(
            output,
            state,
            "failed",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--gpu-lock")
    args = parser.parse_args()
    result = run_finetuned_rerun_supervisor(
        args.protocol,
        state_path=args.state,
        gpu_lock_path=args.gpu_lock,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
