"""Persistent conditional LLZTO fine-tuning and fresh-domain supervisor."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .campaign import load_campaign
from .custom_campaign import validate_custom_campaign
from .dft import prepare_qe_inputs, select_snapshots
from .dft_domain_queue import (
    _ensure_domain_report,
    _passing_numerical_reports,
    _queue_complete,
)
from .finetune import (
    create_finetuned_g2_release_gate,
    create_training_release_gate,
    derive_finetuned_domain_protocol,
    derive_model_campaign,
    predict_snapshot_set_custom,
    train_finetune_phase,
    validate_finetune_protocol,
)
from .md_queue import (
    acquire_gpu_lock,
    active_campaign_pids,
    gpu_compute_pids,
    release_gpu_lock,
    verify_release_gate,
)
from .model_md_queue import run_model_md_queue
from .provenance import atomic_write_json, fingerprint, sha256_file
from .qe_queue import run_queue as run_qe_queue


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


def _update(path: Path, state: dict[str, Any], status: str, **fields: Any) -> None:
    state["status"] = status
    state.update(fields)
    state["updated_unix_time"] = time.time()
    atomic_write_json(path, state)


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _verify_training_report(
    path: Path, *, protocol_sha256: str, phase: str
) -> dict[str, Any]:
    report = _read_json(path)
    _verify_fingerprint(report, "report_fingerprint", "fine-tuning report")
    if (
        report.get("report_kind") != "chgnet-fine-tuning"
        or report.get("phase") != phase
        or report.get("protocol_sha256") != protocol_sha256
        or report.get("fresh_publication_heldout_labels_read") is not False
    ):
        raise RuntimeError(f"fine-tuning report identity mismatch: {path}")
    artifact = report.get("model_artifact", {})
    artifact_path = Path(artifact["path"]).resolve()
    if sha256_file(artifact_path) != artifact.get("sha256"):
        raise RuntimeError(f"fine-tuning model artifact changed: {artifact_path}")
    return report


def _wait_for_idle_gpu_and_train(
    protocol_path: Path,
    *,
    phase_name: str,
    report_path: Path,
    state_path: Path,
    state: dict[str, Any],
    gpu_lock_path: Path,
    poll_seconds: float,
    verify_locks: Callable[[], None],
) -> dict[str, Any]:
    protocol_sha = sha256_file(protocol_path)
    if report_path.is_file():
        return _verify_training_report(
            report_path, protocol_sha256=protocol_sha, phase=phase_name
        )
    lock_handle = None
    while lock_handle is None:
        verify_locks()
        lock_handle = acquire_gpu_lock(gpu_lock_path)
        if lock_handle is None:
            _update(
                state_path,
                state,
                "waiting_for_finetune_gpu_lock",
                waiting={"phase": phase_name, "checked_unix_time": time.time()},
            )
            time.sleep(poll_seconds)
            continue
        campaign_pids = active_campaign_pids()
        compute_pids = gpu_compute_pids()
        if campaign_pids or compute_pids:
            release_gpu_lock(lock_handle)
            lock_handle = None
            _update(
                state_path,
                state,
                "waiting_for_finetune_gpu",
                waiting={
                    "phase": phase_name,
                    "active_campaign_pids": campaign_pids,
                    "gpu_compute_pids": compute_pids,
                    "checked_unix_time": time.time(),
                },
            )
            time.sleep(poll_seconds)
    try:
        verify_locks()
        _update(
            state_path,
            state,
            "training_chgnet",
            current={"phase": phase_name},
            waiting=None,
        )
        train_finetune_phase(protocol_path, phase_name=phase_name, device="cuda")
    finally:
        release_gpu_lock(lock_handle)
    return _verify_training_report(
        report_path, protocol_sha256=protocol_sha, phase=phase_name
    )


def _ensure_model_gate(
    report_path: Path, gate_path: Path, *, gate_id: str
) -> dict[str, Any]:
    if gate_path.is_file():
        return verify_release_gate(gate_path, gate_id=gate_id)
    create_training_release_gate(report_path, gate_id=gate_id, out_path=gate_path)
    return verify_release_gate(gate_path, gate_id=gate_id)


def _ensure_derived_campaign(
    template_path: Path,
    report_path: Path,
    derived_path: Path,
    *,
    model_name: str,
) -> dict[str, Any]:
    if not derived_path.is_file():
        derive_model_campaign(
            template_path,
            report_path,
            out_path=derived_path,
            configured_model_name=model_name,
        )
    campaign = load_campaign(derived_path)
    return validate_custom_campaign(
        derived_path, {run.run_id for run in campaign.runs}
    )


def _model_sampling_complete(path: Path, expected_ids: list[str]) -> bool:
    if not path.is_file():
        return False
    state = _read_json(path)
    if state.get("status") == "failed":
        raise RuntimeError(f"fine-tuned sampling queue failed: {path}")
    if state.get("status") != "complete":
        return False
    if state.get("config", {}).get("run_ids") != expected_ids:
        raise RuntimeError(f"fine-tuned sampling run list changed: {path}")
    jobs = state.get("jobs", {})
    if set(jobs) != set(expected_ids) or any(
        row.get("status") not in {"complete", "already_complete"}
        for row in jobs.values()
    ):
        raise RuntimeError(f"fine-tuned sampling completion is inconsistent: {path}")
    return True


def _ensure_snapshot_selection(
    selection_protocol: Path,
    selection_root: Path,
    *,
    expected_count: int,
) -> dict[str, Any]:
    manifest_path = selection_root / "snapshot_manifest.json"
    if not manifest_path.is_file():
        return select_snapshots(
            selection_protocol, out_dir=selection_root, project_root=_ROOT
        )
    manifest = _read_json(manifest_path)
    _verify_fingerprint(manifest, "snapshot_set_fingerprint", "fallback snapshots")
    if (
        manifest.get("selection_protocol_sha256")
        != sha256_file(selection_protocol)
        or manifest.get("n_snapshots") != expected_count
    ):
        raise RuntimeError(f"fallback snapshot selection differs: {manifest_path}")
    return manifest


def _ensure_qe_set(
    snapshot_manifest: Path,
    runtime_protocol: Path,
    pseudo_manifest: Path,
    *,
    pseudo_dir: Path,
    qe_executable: Path,
    qe_prefix: Path,
    campaign_root: Path,
    queue_state: Path,
    mpi_ranks: int,
    minimum_memory_gib: float,
    poll_seconds: float,
) -> dict[str, Any]:
    campaign_path = campaign_root / "dft_campaign_manifest.json"
    if campaign_path.is_file():
        campaign = _read_json(campaign_path)
        checks = {
            "snapshot": campaign.get("snapshot_manifest_sha256")
            == sha256_file(snapshot_manifest),
            "protocol": campaign.get("dft_protocol_sha256")
            == sha256_file(runtime_protocol),
            "pseudo": campaign.get("pseudopotential_manifest_sha256")
            == sha256_file(pseudo_manifest),
            "binary": campaign.get("pw_executable_sha256")
            == sha256_file(qe_executable),
        }
        if not all(checks.values()):
            raise RuntimeError(f"fallback DFT campaign provenance failed: {campaign_root}")
    else:
        campaign = prepare_qe_inputs(
            snapshot_manifest,
            runtime_protocol,
            pseudo_manifest,
            pseudo_dir=pseudo_dir,
            out_dir=campaign_root,
            qe_executable=qe_executable,
        )
    run_dirs = [campaign_root / row["run_id"] for row in campaign["runs"]]
    if not _queue_complete(queue_state, run_dirs):
        run_qe_queue(
            run_dirs,
            qe_prefix=qe_prefix,
            mpi_ranks=mpi_ranks,
            min_available_memory_gib=minimum_memory_gib,
            poll_seconds=poll_seconds,
            state_path=queue_state,
        )
    if not _queue_complete(queue_state, run_dirs):
        raise RuntimeError(f"fallback DFT queue did not complete: {queue_state}")
    return campaign


def run_finetune_contingency_queue(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
    gpu_lock_path: Path | str = "runs/supervisor/md-gpu.lock",
) -> dict[str, Any]:
    """Wait for the universal decision and execute the frozen fallback if needed."""
    protocol, source = validate_finetune_protocol(protocol_path)
    poll_seconds = float(protocol["reference_method"]["poll_seconds"])
    if not 5 <= poll_seconds <= 60:
        raise ValueError("fine-tuning queue poll_seconds must be between 5 and 60")
    output_state = Path(state_path).resolve()
    gpu_lock = Path(gpu_lock_path).resolve()
    trigger_path = _repo_path(protocol["trigger"]["universal_domain_state"])
    universal_protocol_path = _repo_path(
        protocol["trigger"]["universal_domain_protocol"]
    )
    universal_config = _read_json(universal_protocol_path)
    numerical_state_path = _repo_path(universal_config["numerical_supervisor_state"])
    static_locks = [
        source,
        Path(__file__).resolve(),
        Path(__file__).with_name("finetune.py").resolve(),
        Path(__file__).with_name("custom_campaign.py").resolve(),
        Path(__file__).with_name("model_md_queue.py").resolve(),
        Path(__file__).with_name("dft.py").resolve(),
        Path(__file__).with_name("dft_domain.py").resolve(),
        Path(__file__).with_name("dft_domain_queue.py").resolve(),
        Path(__file__).with_name("qe_queue.py").resolve(),
        Path(__file__).with_name("md_queue.py").resolve(),
        universal_protocol_path,
        _repo_path(protocol["reference_method"]["domain_analysis_protocol"]),
        _repo_path(protocol["expansion_phase"]["sampling_template"]),
        _repo_path(protocol["expansion_phase"]["snapshot_selection_protocol"]),
        _repo_path(protocol["fresh_publication_test"]["sampling_template"]),
        _repo_path(
            protocol["fresh_publication_test"]["snapshot_selection_protocol"]
        ),
    ]
    static_locks.extend(
        _repo_path(record["path"])
        for record in protocol["implementation_locks"].values()
    )
    locked_files = [
        {"path": str(path), "sha256": sha256_file(path)} for path in static_locks
    ]

    def verify_locks() -> None:
        for record in locked_files:
            if sha256_file(record["path"]) != record["sha256"]:
                raise RuntimeError(
                    f"fine-tuning contingency locked file changed: {record['path']}"
                )

    config = {
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "trigger_state_path": str(trigger_path),
        "gpu_lock_path": str(gpu_lock),
        "locked_files": locked_files,
    }
    queue_fingerprint = fingerprint(config)
    if output_state.is_file():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"fine-tuning queue configuration changed: {output_state}")
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": queue_fingerprint,
            "config": config,
            "created_unix_time": time.time(),
            "stages": {},
        }
        _update(output_state, state, "created")

    try:
        trigger_statuses = set(protocol["trigger"]["trigger_statuses"])
        while True:
            verify_locks()
            if trigger_path.is_file():
                universal_state = _read_json(trigger_path)
                status = str(universal_state.get("status", "missing_status"))
                if status == protocol["trigger"]["not_triggered_status"]:
                    _update(
                        output_state,
                        state,
                        "complete",
                        disposition="not_triggered_universal_domain_pass",
                        universal_domain_state_sha256=sha256_file(trigger_path),
                        waiting=None,
                    )
                    return state
                if status in trigger_statuses:
                    state["trigger"] = {
                        "status": status,
                        "state_path": str(trigger_path),
                        "state_sha256": sha256_file(trigger_path),
                    }
                    break
                if status == "failed":
                    raise RuntimeError("universal domain supervisor failed unexpectedly")
            _update(
                output_state,
                state,
                "waiting_for_universal_domain_decision",
                waiting={"path": str(trigger_path), "checked_unix_time": time.time()},
            )
            time.sleep(poll_seconds)

        numerical_state = _read_json(numerical_state_path)
        if numerical_state.get("status") != "complete":
            raise RuntimeError("fallback trigger occurred before numerical completion")
        numerical_reports = _passing_numerical_reports(
            numerical_state, universal_config
        )
        runtime_protocol = _repo_path(
            protocol["reference_method"]["runtime_dft_protocol"]
        )
        if not runtime_protocol.is_file():
            raise FileNotFoundError(runtime_protocol)
        pseudo_manifest = _repo_path(
            protocol["reference_method"]["pseudopotential_manifest"]
        )
        pseudo_dir = Path(
            universal_config["pseudopotential_manifest"]["local_directory"]
        ).resolve()
        qe_prefix = Path(protocol["reference_method"]["qe_prefix"]).resolve()
        qe_executable = qe_prefix / "bin/pw.x"
        mpi_ranks = int(protocol["reference_method"]["mpi_ranks"])
        minimum_memory = float(
            protocol["reference_method"]["minimum_memory_gib"]
        )

        bootstrap = protocol["bootstrap_phase"]
        bootstrap_report_path = _repo_path(bootstrap["output_report"])
        bootstrap_report = _wait_for_idle_gpu_and_train(
            source,
            phase_name="bootstrap_phase",
            report_path=bootstrap_report_path,
            state_path=output_state,
            state=state,
            gpu_lock_path=gpu_lock,
            poll_seconds=poll_seconds,
            verify_locks=verify_locks,
        )
        state["stages"]["bootstrap_training"] = {
            "status": "complete",
            "report_path": str(bootstrap_report_path),
            "report_sha256": sha256_file(bootstrap_report_path),
            "model_state_dict_sha256": bootstrap_report["model_artifact"][
                "state_dict_sha256"
            ],
        }
        bootstrap_gate_path = _repo_path(bootstrap["release_gate"])
        _ensure_model_gate(
            bootstrap_report_path,
            bootstrap_gate_path,
            gate_id="g2-finetune-bootstrap",
        )

        expansion = protocol["expansion_phase"]
        training_campaign_path = _repo_path(expansion["derived_sampling_protocol"])
        training_custom = _ensure_derived_campaign(
            _repo_path(expansion["sampling_template"]),
            bootstrap_report_path,
            training_campaign_path,
            model_name="LLZTO-CHGNet-bootstrap-v1",
        )
        training_campaign = load_campaign(training_campaign_path)
        training_run_ids = [run.run_id for run in training_campaign.runs]
        training_sampling_state = _repo_path(expansion["sampling_queue_state"])
        if not _model_sampling_complete(training_sampling_state, training_run_ids):
            _update(
                output_state,
                state,
                "running_finetune_training_coordinate_sampling",
                current={"queue_state": str(training_sampling_state)},
            )
            run_model_md_queue(
                training_campaign_path,
                training_run_ids,
                release_gate_path=bootstrap_gate_path,
                release_gate_id="g2-finetune-bootstrap",
                poll_seconds=poll_seconds,
                state_path=training_sampling_state,
                gpu_lock_path=gpu_lock,
            )
        state["stages"]["training_coordinate_sampling"] = {
            "status": "complete",
            "campaign_protocol_sha256": training_custom["protocol_sha256"],
            "queue_state_path": str(training_sampling_state),
            "queue_state_sha256": sha256_file(training_sampling_state),
        }

        training_selection_protocol = _repo_path(
            expansion["snapshot_selection_protocol"]
        )
        training_selection_root = _repo_path(expansion["snapshot_selection_root"])
        training_selection = _ensure_snapshot_selection(
            training_selection_protocol,
            training_selection_root,
            expected_count=int(expansion["expected_new_records"]),
        )
        training_manifest = training_selection_root / "snapshot_manifest.json"
        state["stages"]["training_snapshot_selection"] = {
            "status": "complete",
            "n_snapshots": training_selection["n_snapshots"],
            "manifest_path": str(training_manifest),
            "manifest_sha256": sha256_file(training_manifest),
        }
        training_dft_root = _repo_path(expansion["dft_campaign_root"])
        training_dft_state = _repo_path(expansion["dft_queue_state"])
        _update(
            output_state,
            state,
            "running_finetune_training_dft",
            current={"queue_state": str(training_dft_state)},
        )
        training_dft = _ensure_qe_set(
            training_manifest,
            runtime_protocol,
            pseudo_manifest,
            pseudo_dir=pseudo_dir,
            qe_executable=qe_executable,
            qe_prefix=qe_prefix,
            campaign_root=training_dft_root,
            queue_state=training_dft_state,
            mpi_ranks=mpi_ranks,
            minimum_memory_gib=minimum_memory,
            poll_seconds=poll_seconds,
        )
        state["stages"]["training_dft"] = {
            "status": "complete",
            "n_runs": training_dft["n_runs"],
            "queue_state_path": str(training_dft_state),
            "queue_state_sha256": sha256_file(training_dft_state),
        }

        final_phase = protocol["final_training_phase"]
        final_report_path = _repo_path(final_phase["output_report"])
        final_report = _wait_for_idle_gpu_and_train(
            source,
            phase_name="final_training_phase",
            report_path=final_report_path,
            state_path=output_state,
            state=state,
            gpu_lock_path=gpu_lock,
            poll_seconds=poll_seconds,
            verify_locks=verify_locks,
        )
        state["stages"]["final_training"] = {
            "status": "complete",
            "report_path": str(final_report_path),
            "report_sha256": sha256_file(final_report_path),
            "model_state_dict_sha256": final_report["model_artifact"][
                "state_dict_sha256"
            ],
        }
        final_gate_path = _repo_path(final_phase["release_gate"])
        _ensure_model_gate(
            final_report_path,
            final_gate_path,
            gate_id="g2-finetune-final-model",
        )

        fresh = protocol["fresh_publication_test"]
        heldout_campaign_path = _repo_path(fresh["derived_sampling_protocol"])
        heldout_custom = _ensure_derived_campaign(
            _repo_path(fresh["sampling_template"]),
            final_report_path,
            heldout_campaign_path,
            model_name="LLZTO-CHGNet-finetuned-v1",
        )
        heldout_campaign = load_campaign(heldout_campaign_path)
        heldout_run_ids = [run.run_id for run in heldout_campaign.runs]
        heldout_sampling_state = _repo_path(fresh["sampling_queue_state"])
        if not _model_sampling_complete(heldout_sampling_state, heldout_run_ids):
            _update(
                output_state,
                state,
                "running_finetuned_heldout_coordinate_sampling",
                current={"queue_state": str(heldout_sampling_state)},
            )
            run_model_md_queue(
                heldout_campaign_path,
                heldout_run_ids,
                release_gate_path=final_gate_path,
                release_gate_id="g2-finetune-final-model",
                poll_seconds=poll_seconds,
                state_path=heldout_sampling_state,
                gpu_lock_path=gpu_lock,
            )
        state["stages"]["fresh_heldout_coordinate_sampling"] = {
            "status": "complete",
            "campaign_protocol_sha256": heldout_custom["protocol_sha256"],
            "queue_state_path": str(heldout_sampling_state),
            "queue_state_sha256": sha256_file(heldout_sampling_state),
        }

        heldout_selection_protocol = _repo_path(fresh["snapshot_selection_protocol"])
        heldout_selection_root = _repo_path(fresh["snapshot_selection_root"])
        heldout_selection = _ensure_snapshot_selection(
            heldout_selection_protocol,
            heldout_selection_root,
            expected_count=int(fresh["expected_records"]),
        )
        heldout_manifest = heldout_selection_root / "snapshot_manifest.json"
        state["stages"]["fresh_heldout_selection"] = {
            "status": "complete",
            "n_snapshots": heldout_selection["n_snapshots"],
            "manifest_path": str(heldout_manifest),
            "manifest_sha256": sha256_file(heldout_manifest),
        }
        heldout_dft_root = _repo_path(fresh["dft_campaign_root"])
        heldout_dft_state = _repo_path(fresh["dft_queue_state"])
        _update(
            output_state,
            state,
            "running_finetuned_heldout_dft",
            current={"queue_state": str(heldout_dft_state)},
        )
        heldout_dft = _ensure_qe_set(
            heldout_manifest,
            runtime_protocol,
            pseudo_manifest,
            pseudo_dir=pseudo_dir,
            qe_executable=qe_executable,
            qe_prefix=qe_prefix,
            campaign_root=heldout_dft_root,
            queue_state=heldout_dft_state,
            mpi_ranks=mpi_ranks,
            minimum_memory_gib=minimum_memory,
            poll_seconds=poll_seconds,
        )
        state["stages"]["fresh_heldout_dft"] = {
            "status": "complete",
            "n_runs": heldout_dft["n_runs"],
            "queue_state_path": str(heldout_dft_state),
            "queue_state_sha256": sha256_file(heldout_dft_state),
        }

        derived_analysis_path = _repo_path(fresh["analysis_protocol"])
        if not derived_analysis_path.is_file():
            derive_finetuned_domain_protocol(
                _repo_path(protocol["reference_method"]["domain_analysis_protocol"]),
                final_report_path,
                heldout_selection_protocol,
                out_path=derived_analysis_path,
            )
        derived_analysis = _read_json(derived_analysis_path)
        _verify_fingerprint(
            derived_analysis,
            "derivation_fingerprint",
            "fine-tuned domain protocol",
        )
        prediction_root = _repo_path(fresh["prediction_root"])
        _update(output_state, state, "predicting_finetuned_heldout")
        prediction = predict_snapshot_set_custom(
            heldout_manifest,
            derived_analysis_path,
            final_report["model_artifact"]["path"],
            set_id="fine-tuned-publication-heldout",
            out_dir=prediction_root,
            device="cpu",
        )
        state["stages"]["fresh_heldout_prediction"] = {
            "status": "complete",
            "n_predictions": prediction["n_predictions"],
            "manifest_path": str(prediction_root / "prediction_manifest.json"),
            "manifest_sha256": sha256_file(
                prediction_root / "prediction_manifest.json"
            ),
        }
        domain_report_path = _repo_path(fresh["domain_report"])
        domain_report = _ensure_domain_report(
            snapshot_manifest=heldout_manifest,
            dft_campaign_root=heldout_dft_root,
            prediction_root=prediction_root,
            analysis_protocol=derived_analysis_path,
            set_id="fine-tuned-publication-heldout",
            numerical_reports=numerical_reports,
            output_path=domain_report_path,
        )
        state["stages"]["fresh_heldout_domain"] = {
            "status": "pass" if domain_report["domain_gate_pass"] else "fail",
            "path": str(domain_report_path),
            "sha256": sha256_file(domain_report_path),
        }
        if not domain_report["domain_gate_pass"]:
            _update(
                output_state,
                state,
                "blocked_finetuned_domain_failure",
                blocker={"failure_action": domain_report["failure_action"]},
            )
            return state

        release = protocol["release_and_rerun"]
        release_path = _repo_path(release["release_gate"])
        if not release_path.is_file():
            create_finetuned_g2_release_gate(
                derived_analysis_path,
                domain_report_path,
                final_report_path,
                numerical_reports=numerical_reports,
                gate_id=release["gate_id"],
                out_path=release_path,
            )
        release_gate = verify_release_gate(
            release_path, gate_id=release["gate_id"]
        )
        state["stages"]["finetuned_g2_release"] = {
            "status": "pass",
            "path": str(release_path),
            "sha256": sha256_file(release_path),
            "gate": release_gate,
        }
        _update(
            output_state,
            state,
            "complete",
            disposition="fine_tuned_domain_pass_requires_all_transport_reruns",
            required_reruns=release["required_reruns"],
            current=None,
            waiting=None,
        )
        return state
    except BaseException as exc:
        _update(
            output_state,
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
    parser.add_argument("--gpu-lock", default="runs/supervisor/md-gpu.lock")
    args = parser.parse_args()
    result = run_finetune_contingency_queue(
        args.protocol,
        state_path=args.state,
        gpu_lock_path=args.gpu_lock,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
