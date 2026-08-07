"""Persistent LLZTO feasibility/heldout DFT-domain supervisor."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .dft import prepare_qe_inputs, select_snapshots
from .dft_domain import (
    build_domain_report_from_files,
    create_g2_release_gate,
    create_sampling_release_gate,
    predict_snapshot_set,
)
from .md_queue import verify_release_gate
from .provenance import atomic_write_json, fingerprint, sha256_file
from .qe_queue import run_queue


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


def _update_state(path: Path, state: dict[str, Any], status: str, **fields: Any) -> None:
    state["status"] = status
    state.update(fields)
    state["updated_unix_time"] = time.time()
    atomic_write_json(path, state)


def _write_or_verify(path: Path, payload: dict[str, Any], *, label: str) -> None:
    if path.exists():
        if _read_json(path) != payload:
            raise RuntimeError(f"existing {label} differs: {path}")
        return
    atomic_write_json(path, payload)


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _verify_locked_files(records: list[dict[str, str]]) -> None:
    for record in records:
        path = Path(record["path"]).resolve()
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"domain-supervisor locked file changed: {path}")


def _queue_complete(path: Path, expected_run_dirs: list[Path]) -> bool:
    if not path.is_file():
        return False
    state = _read_json(path)
    if state.get("status") == "failed":
        raise RuntimeError(f"nested queue failed: {path}")
    if state.get("status") != "complete":
        return False
    configured = {
        str(Path(value).resolve())
        for value in state.get("config", {}).get("run_dirs", [])
    }
    expected = {str(path.resolve()) for path in expected_run_dirs}
    if configured != expected:
        raise RuntimeError(f"nested queue run-directory mismatch: {path}")
    complete_states = {
        "complete",
        "already_labelled",
        "collected_existing_output",
    }
    jobs = state.get("jobs", {})
    if len(jobs) != len(expected) or any(
        row.get("status") not in complete_states for row in jobs.values()
    ):
        raise RuntimeError(f"nested queue completion is inconsistent: {path}")
    return True


def _wait_for_status(
    path: Path,
    expected_status: str,
    *,
    state_path: Path,
    state: dict[str, Any],
    stage: str,
    poll_seconds: float,
    locked_files: list[dict[str, str]],
) -> dict[str, Any]:
    while True:
        _verify_locked_files(locked_files)
        if path.is_file():
            payload = _read_json(path)
            status = payload.get("status")
            if status == expected_status:
                state.pop("waiting", None)
                return payload
            if status in {
                "failed",
                "blocked_no_converged_kpoint",
                "blocked_no_converged_scf_threshold",
                "blocked_mpi_nonequivalence",
            }:
                raise RuntimeError(f"upstream supervisor stopped as {status}: {path}")
        _update_state(
            state_path,
            state,
            "waiting_for_upstream",
            waiting={
                "stage": stage,
                "path": str(path),
                "expected_status": expected_status,
                "checked_unix_time": time.time(),
            },
        )
        time.sleep(poll_seconds)


def _wait_for_md_queue(
    path: Path,
    *,
    state_path: Path,
    state: dict[str, Any],
    poll_seconds: float,
    locked_files: list[dict[str, str]],
) -> dict[str, Any]:
    while True:
        _verify_locked_files(locked_files)
        if path.is_file():
            payload = _read_json(path)
            if payload.get("status") == "complete":
                state.pop("waiting", None)
                return payload
            if payload.get("status") == "failed":
                raise RuntimeError(f"domain-sampling MD queue failed: {path}")
        _update_state(
            state_path,
            state,
            "waiting_for_domain_sampling_md",
            waiting={
                "stage": "publication-heldout-coordinate-sampling",
                "queue_state_path": str(path),
                "checked_unix_time": time.time(),
            },
        )
        time.sleep(poll_seconds)


def _ensure_qe_campaign(
    snapshot_manifest: Path,
    dft_protocol: Path,
    pseudo_manifest: Path,
    *,
    pseudo_dir: Path,
    qe_executable: Path,
    output_root: Path,
) -> dict[str, Any]:
    campaign_path = output_root / "dft_campaign_manifest.json"
    if campaign_path.is_file():
        campaign = _read_json(campaign_path)
        checks = {
            "snapshot": campaign.get("snapshot_manifest_sha256")
            == sha256_file(snapshot_manifest),
            "protocol": campaign.get("dft_protocol_sha256")
            == sha256_file(dft_protocol),
            "pseudo": campaign.get("pseudopotential_manifest_sha256")
            == sha256_file(pseudo_manifest),
            "binary": campaign.get("pw_executable_sha256")
            == sha256_file(qe_executable),
        }
        if not all(checks.values()):
            raise RuntimeError(f"DFT campaign provenance failed: {output_root}")
        return campaign
    return prepare_qe_inputs(
        snapshot_manifest,
        dft_protocol,
        pseudo_manifest,
        pseudo_dir=pseudo_dir,
        out_dir=output_root,
        qe_executable=qe_executable,
    )


def build_runtime_domain_dft_protocol(
    selected_settings: dict[str, Any],
    configuration: dict[str, Any],
    numerical_state: dict[str, Any],
) -> dict[str, Any]:
    numerical_fields = (
        "ecutwfc_ry",
        "ecutrho_ry",
        "kpoints",
        "conv_thr_ry",
        "electron_maxstep",
        "mixing_mode",
        "mixing_beta",
        "diagonalization",
    )
    settings = {field: selected_settings[field] for field in numerical_fields}
    settings.update(
        label="selected-final-domain",
        purpose=(
            "final independent DFT labels for feasibility and publication-heldout "
            "CHGNet-domain tests"
        ),
    )
    return {
        "schema_version": "1.0",
        "protocol_id": "llzto-qe-final-domain-v1",
        "selection_is_model_blind": True,
        "derivation_rule": (
            "Numerical fields are copied mechanically from the passed SCF "
            "decision after complete MPI equivalence; no model error is read."
        ),
        "numerical_supervisor_protocol_path": numerical_state["config"][
            "protocol_path"
        ],
        "numerical_supervisor_protocol_sha256": numerical_state["config"][
            "protocol_sha256"
        ],
        "selected_scf_decision_path": numerical_state["stages"]["scf_decision"][
            "path"
        ],
        "selected_scf_decision_sha256": numerical_state["stages"]["scf_decision"][
            "sha256"
        ],
        "mpi_report_path": numerical_state["stages"]["mpi_reproducibility"][
            "path"
        ],
        "mpi_report_sha256": numerical_state["stages"]["mpi_reproducibility"][
            "sha256"
        ],
        "execution_environment": configuration["execution_environment"],
        "physics": configuration["physics"],
        "calculations": [settings],
    }


def _passing_numerical_reports(
    numerical_state: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Path]:
    stages = numerical_state["stages"]
    kpoint_candidates = [
        stages.get("kpoint_gamma_2x2x2"),
        stages.get("kpoint_2x2x2_3x3x3"),
    ]
    scf_candidates = [
        stages.get("scf_comparison_0"),
        stages.get("scf_comparison_1"),
    ]

    def passed_path(candidates: list[Any], name: str) -> Path:
        passing = [row for row in candidates if row and row.get("status") == "pass"]
        if len(passing) != 1:
            raise RuntimeError(f"expected one passing {name} convergence report")
        path = Path(passing[0]["path"]).resolve()
        if sha256_file(path) != passing[0]["sha256"]:
            raise RuntimeError(f"{name} report hash mismatch")
        return path

    cutoff = _repo_path(configuration["numerical_reports"]["cutoff"])
    cutoff_payload = _read_json(cutoff)
    if cutoff_payload.get("numerically_converged") is not True:
        raise RuntimeError("selected cutoff convergence report did not pass")
    return {
        "cutoff": cutoff,
        "kpoint": passed_path(kpoint_candidates, "kpoint"),
        "scf": passed_path(scf_candidates, "SCF"),
    }


def _ensure_domain_report(
    *,
    snapshot_manifest: Path,
    dft_campaign_root: Path,
    prediction_root: Path,
    analysis_protocol: Path,
    set_id: str,
    numerical_reports: dict[str, Path],
    output_path: Path,
) -> dict[str, Any]:
    if output_path.is_file():
        report = _read_json(output_path)
        _verify_fingerprint(report, "report_fingerprint", f"{set_id} domain report")
        if report.get("set_id") != set_id:
            raise RuntimeError(f"wrong domain set in {output_path}")
        return report
    return build_domain_report_from_files(
        snapshot_manifest,
        dft_campaign_root,
        prediction_root,
        analysis_protocol,
        set_id=set_id,
        numerical_reports=numerical_reports,
        out_path=output_path,
    )


def _run_final_dft_set(
    *,
    snapshot_manifest: Path,
    runtime_protocol: Path,
    pseudo_manifest: Path,
    pseudo_dir: Path,
    qe_executable: Path,
    qe_prefix: Path,
    campaign_root: Path,
    queue_state: Path,
    mpi_ranks: int,
    min_memory_gib: float,
    poll_seconds: float,
) -> dict[str, Any]:
    campaign = _ensure_qe_campaign(
        snapshot_manifest,
        runtime_protocol,
        pseudo_manifest,
        pseudo_dir=pseudo_dir,
        qe_executable=qe_executable,
        output_root=campaign_root,
    )
    run_dirs = [campaign_root / row["run_id"] for row in campaign["runs"]]
    if not _queue_complete(queue_state, run_dirs):
        run_queue(
            run_dirs,
            qe_prefix=qe_prefix,
            mpi_ranks=mpi_ranks,
            min_available_memory_gib=min_memory_gib,
            poll_seconds=poll_seconds,
            state_path=queue_state,
        )
    if not _queue_complete(queue_state, run_dirs):
        raise RuntimeError(f"final domain QE queue did not complete: {queue_state}")
    return campaign


def run_domain_supervisor(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
) -> dict[str, Any]:
    source = Path(protocol_path).resolve()
    configuration = _read_json(source)
    if configuration.get("schema_version") != "1.0":
        raise ValueError("domain supervisor protocol schema_version must be '1.0'")
    poll_seconds = float(configuration["resources"]["poll_seconds"])
    qe_prefix = Path(configuration["execution_environment"]["qe_prefix"]).resolve()
    qe_executable = qe_prefix / "bin/pw.x"
    pseudo_manifest = _repo_path(configuration["pseudopotential_manifest"]["path"])
    pseudo_dir = Path(configuration["pseudopotential_manifest"]["local_directory"])
    analysis_protocol = _repo_path(configuration["analysis_protocol"]["path"])
    feasibility_manifest = _repo_path(configuration["feasibility"]["snapshot_manifest"])
    heldout_protocol = _repo_path(configuration["heldout"]["selection_protocol"])
    numerical_state_path = _repo_path(configuration["numerical_supervisor_state"])
    locked_paths = [
        source,
        pseudo_manifest,
        analysis_protocol,
        feasibility_manifest,
        heldout_protocol,
        Path(__file__).resolve(),
        Path(__file__).with_name("dft.py").resolve(),
        Path(__file__).with_name("dft_domain.py").resolve(),
        Path(__file__).with_name("qe_queue.py").resolve(),
        Path(__file__).with_name("md_queue.py").resolve(),
    ]
    locked_files = [
        {"path": str(path), "sha256": sha256_file(path)} for path in locked_paths
    ]
    declarations = {
        pseudo_manifest: configuration["pseudopotential_manifest"]["sha256"],
        analysis_protocol: configuration["analysis_protocol"]["sha256"],
        feasibility_manifest: configuration["feasibility"][
            "snapshot_manifest_sha256"
        ],
        heldout_protocol: configuration["heldout"]["selection_protocol_sha256"],
        qe_executable: configuration["execution_environment"][
            "pw_executable_sha256"
        ],
    }
    for path, expected in declarations.items():
        if sha256_file(path) != expected:
            raise RuntimeError(f"declared domain-supervisor hash mismatch: {path}")
    output_state = Path(state_path).resolve()
    config_record = {
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "locked_files": locked_files,
        "qe_executable_path": str(qe_executable),
        "qe_executable_sha256": sha256_file(qe_executable),
    }
    queue_fingerprint = fingerprint(config_record)
    if output_state.exists():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"domain supervisor configuration changed: {output_state}")
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": queue_fingerprint,
            "config": config_record,
            "status": "created",
            "created_unix_time": time.time(),
            "stages": {},
        }
        atomic_write_json(output_state, state)
    try:
        numerical_state = _wait_for_status(
            numerical_state_path,
            "complete",
            state_path=output_state,
            state=state,
            stage="numerical-convergence-and-mpi",
            poll_seconds=poll_seconds,
            locked_files=locked_files,
        )
        selected_settings = numerical_state.get("selected_settings")
        if not isinstance(selected_settings, dict):
            raise RuntimeError("numerical supervisor has no selected settings")
        scf_decision_path = Path(
            numerical_state["stages"]["scf_decision"]["path"]
        ).resolve()
        scf_decision = _read_json(scf_decision_path)
        _verify_fingerprint(scf_decision, "decision_fingerprint", "SCF decision")
        if (
            scf_decision.get("can_continue") is not True
            or scf_decision.get("selected_settings") != selected_settings
        ):
            raise RuntimeError("selected numerical settings do not match SCF decision")
        mpi_report_path = Path(
            numerical_state["stages"]["mpi_reproducibility"]["path"]
        ).resolve()
        mpi_report = _read_json(mpi_report_path)
        _verify_fingerprint(mpi_report, "report_fingerprint", "MPI report")
        if mpi_report.get("mpi_equivalence_gate_pass") is not True:
            raise RuntimeError("MPI report did not pass")
        numerical_reports = _passing_numerical_reports(
            numerical_state, configuration
        )

        runtime_protocol_path = _repo_path(configuration["runtime_dft_protocol"])
        runtime_protocol = build_runtime_domain_dft_protocol(
            selected_settings, configuration, numerical_state
        )
        _write_or_verify(
            runtime_protocol_path, runtime_protocol, label="runtime domain DFT protocol"
        )
        state["stages"]["runtime_protocol"] = {
            "status": "complete",
            "path": str(runtime_protocol_path),
            "sha256": sha256_file(runtime_protocol_path),
        }

        feasibility_root = _repo_path(configuration["feasibility"]["dft_root"])
        feasibility_queue = _repo_path(
            configuration["feasibility"]["qe_queue_state"]
        )
        _update_state(
            output_state,
            state,
            "running_feasibility_dft",
            current={"queue_state_path": str(feasibility_queue)},
        )
        feasibility_campaign = _run_final_dft_set(
            snapshot_manifest=feasibility_manifest,
            runtime_protocol=runtime_protocol_path,
            pseudo_manifest=pseudo_manifest,
            pseudo_dir=pseudo_dir,
            qe_executable=qe_executable,
            qe_prefix=qe_prefix,
            campaign_root=feasibility_root,
            queue_state=feasibility_queue,
            mpi_ranks=int(configuration["resources"]["mpi_ranks"]),
            min_memory_gib=float(configuration["resources"]["minimum_memory_gib"]),
            poll_seconds=poll_seconds,
        )
        state["stages"]["feasibility_dft"] = {
            "status": "complete",
            "n_runs": feasibility_campaign["n_runs"],
            "queue_state_path": str(feasibility_queue),
            "queue_state_sha256": sha256_file(feasibility_queue),
        }

        feasibility_prediction = _repo_path(
            configuration["feasibility"]["prediction_root"]
        )
        _update_state(output_state, state, "predicting_feasibility_chgnet")
        prediction = predict_snapshot_set(
            feasibility_manifest,
            analysis_protocol,
            set_id="feasibility",
            out_dir=feasibility_prediction,
            device=configuration["resources"]["prediction_device"],
        )
        state["stages"]["feasibility_prediction"] = {
            "status": "complete",
            "n_predictions": prediction["n_predictions"],
            "manifest_path": str(feasibility_prediction / "prediction_manifest.json"),
            "manifest_sha256": sha256_file(
                feasibility_prediction / "prediction_manifest.json"
            ),
        }
        feasibility_report_path = _repo_path(
            configuration["feasibility"]["domain_report"]
        )
        feasibility_report = _ensure_domain_report(
            snapshot_manifest=feasibility_manifest,
            dft_campaign_root=feasibility_root,
            prediction_root=feasibility_prediction,
            analysis_protocol=analysis_protocol,
            set_id="feasibility",
            numerical_reports=numerical_reports,
            output_path=feasibility_report_path,
        )
        state["stages"]["feasibility_domain"] = {
            "status": "pass"
            if feasibility_report["domain_gate_pass"]
            else "fail",
            "path": str(feasibility_report_path),
            "sha256": sha256_file(feasibility_report_path),
        }
        if not feasibility_report["domain_gate_pass"]:
            _update_state(
                output_state,
                state,
                "blocked_feasibility_domain_failure",
                blocker={"failure_action": feasibility_report["failure_action"]},
            )
            return state

        sampling_gate_path = _repo_path(configuration["sampling_release_gate"])
        if sampling_gate_path.is_file():
            sampling_gate = verify_release_gate(
                sampling_gate_path, gate_id="g2-feasibility-domain-sampling"
            )
        else:
            sampling_gate = create_sampling_release_gate(
                analysis_protocol,
                domain_report=feasibility_report_path,
                numerical_reports=numerical_reports,
                out_path=sampling_gate_path,
            )
        state["stages"]["sampling_release"] = {
            "status": "pass",
            "path": str(sampling_gate_path),
            "sha256": sha256_file(sampling_gate_path),
            "gate_fingerprint": sampling_gate["gate_fingerprint"],
        }

        md_queue_path = _repo_path(configuration["heldout"]["md_queue_state"])
        _wait_for_md_queue(
            md_queue_path,
            state_path=output_state,
            state=state,
            poll_seconds=poll_seconds,
            locked_files=locked_files,
        )
        state["stages"]["heldout_sampling_md"] = {
            "status": "complete",
            "queue_state_path": str(md_queue_path),
            "queue_state_sha256": sha256_file(md_queue_path),
        }

        heldout_selection_root = _repo_path(
            configuration["heldout"]["selection_root"]
        )
        heldout_manifest = heldout_selection_root / "snapshot_manifest.json"
        if heldout_manifest.is_file():
            selected = _read_json(heldout_manifest)
            if (
                selected.get("selection_protocol_sha256")
                != sha256_file(heldout_protocol)
                or selected.get("n_snapshots") != 30
            ):
                raise RuntimeError("existing heldout snapshot selection differs")
        else:
            selected = select_snapshots(
                heldout_protocol,
                out_dir=heldout_selection_root,
                project_root=_ROOT,
            )
        state["stages"]["heldout_selection"] = {
            "status": "complete",
            "n_snapshots": selected["n_snapshots"],
            "manifest_path": str(heldout_manifest),
            "manifest_sha256": sha256_file(heldout_manifest),
        }

        heldout_root = _repo_path(configuration["heldout"]["dft_root"])
        heldout_queue = _repo_path(configuration["heldout"]["qe_queue_state"])
        _update_state(
            output_state,
            state,
            "running_heldout_dft",
            current={"queue_state_path": str(heldout_queue)},
        )
        heldout_campaign = _run_final_dft_set(
            snapshot_manifest=heldout_manifest,
            runtime_protocol=runtime_protocol_path,
            pseudo_manifest=pseudo_manifest,
            pseudo_dir=pseudo_dir,
            qe_executable=qe_executable,
            qe_prefix=qe_prefix,
            campaign_root=heldout_root,
            queue_state=heldout_queue,
            mpi_ranks=int(configuration["resources"]["mpi_ranks"]),
            min_memory_gib=float(configuration["resources"]["minimum_memory_gib"]),
            poll_seconds=poll_seconds,
        )
        state["stages"]["heldout_dft"] = {
            "status": "complete",
            "n_runs": heldout_campaign["n_runs"],
            "queue_state_path": str(heldout_queue),
            "queue_state_sha256": sha256_file(heldout_queue),
        }

        heldout_prediction = _repo_path(
            configuration["heldout"]["prediction_root"]
        )
        _update_state(output_state, state, "predicting_heldout_chgnet")
        heldout_prediction_manifest = predict_snapshot_set(
            heldout_manifest,
            analysis_protocol,
            set_id="publication-heldout",
            out_dir=heldout_prediction,
            device=configuration["resources"]["prediction_device"],
        )
        state["stages"]["heldout_prediction"] = {
            "status": "complete",
            "n_predictions": heldout_prediction_manifest["n_predictions"],
            "manifest_path": str(heldout_prediction / "prediction_manifest.json"),
            "manifest_sha256": sha256_file(
                heldout_prediction / "prediction_manifest.json"
            ),
        }
        heldout_report_path = _repo_path(configuration["heldout"]["domain_report"])
        heldout_report = _ensure_domain_report(
            snapshot_manifest=heldout_manifest,
            dft_campaign_root=heldout_root,
            prediction_root=heldout_prediction,
            analysis_protocol=analysis_protocol,
            set_id="publication-heldout",
            numerical_reports=numerical_reports,
            output_path=heldout_report_path,
        )
        state["stages"]["heldout_domain"] = {
            "status": "pass" if heldout_report["domain_gate_pass"] else "fail",
            "path": str(heldout_report_path),
            "sha256": sha256_file(heldout_report_path),
        }
        if not heldout_report["domain_gate_pass"]:
            _update_state(
                output_state,
                state,
                "blocked_heldout_domain_failure",
                blocker={"failure_action": heldout_report["failure_action"]},
            )
            return state

        g2_path = _repo_path(configuration["g2_release_gate"])
        if g2_path.is_file():
            g2 = verify_release_gate(g2_path, gate_id="g2-potential-domain")
        else:
            g2 = create_g2_release_gate(
                analysis_protocol,
                domain_reports={
                    "feasibility": feasibility_report_path,
                    "publication-heldout": heldout_report_path,
                },
                numerical_reports=numerical_reports,
                out_path=g2_path,
            )
        state["stages"]["g2_release"] = {
            "status": "pass",
            "path": str(g2_path),
            "sha256": sha256_file(g2_path),
            "gate_fingerprint": g2["gate_fingerprint"],
        }
        state.pop("current", None)
        state.pop("waiting", None)
        _update_state(
            output_state,
            state,
            "complete",
            completed_unix_time=time.time(),
        )
        return state
    except BaseException as exc:
        _update_state(
            output_state,
            state,
            "failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    result = run_domain_supervisor(args.protocol, state_path=args.state)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
