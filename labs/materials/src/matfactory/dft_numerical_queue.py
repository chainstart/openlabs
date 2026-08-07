"""Persistent, result-blind supervisor for LLZTO QE numerical convergence."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .dft import prepare_qe_inputs
from .dft_convergence import compare_qe_settings, write_convergence_report
from .dft_decision import choose_adjacent_setting
from .dft_mpi import build_mpi_report
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


def _resource_evidence_hashes(protocol: dict[str, Any]) -> dict[Path, str]:
    """Collect every hash-bearing pre-SCF resource artifact in a k-point protocol."""
    guard = protocol.get("resource_guard", {})
    declared: dict[Path, str] = {}
    interrupted = guard.get("unsafe_default_attempt_interruption")
    if isinstance(interrupted, dict):
        declared[_repo_path(interrupted["path"])] = str(interrupted["sha256"])
    for probe in guard.get("pre_scf_probes", []):
        for prefix in ("input", "output"):
            declared[_repo_path(probe[f"{prefix}_path"])] = str(
                probe[f"{prefix}_sha256"]
            )
    return declared


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


def _verify_locked_files(records: list[dict[str, str]]) -> None:
    for record in records:
        path = Path(record["path"]).resolve()
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"numerical-supervisor locked file changed: {path}")


def _queue_complete(path: Path, expected_run_dirs: list[Path]) -> bool:
    if not path.is_file():
        return False
    state = _read_json(path)
    if state.get("status") == "failed":
        raise RuntimeError(f"nested QE queue failed: {path}")
    if state.get("status") != "complete":
        return False
    configured = {
        str(Path(value).resolve())
        for value in state.get("config", {}).get("run_dirs", [])
    }
    expected = {str(path.resolve()) for path in expected_run_dirs}
    if configured != expected:
        raise RuntimeError(f"nested QE queue run-directory mismatch: {path}")
    jobs = state.get("jobs", {})
    complete_states = {
        "complete",
        "already_labelled",
        "collected_existing_output",
    }
    if len(jobs) != len(expected) or any(
        row.get("status") not in complete_states for row in jobs.values()
    ):
        raise RuntimeError(f"nested QE queue completion is inconsistent: {path}")
    return True


def _wait_for_queue(
    path: Path,
    expected_run_dirs: list[Path],
    *,
    state_path: Path,
    state: dict[str, Any],
    stage: str,
    poll_seconds: float,
    locked_files: list[dict[str, str]],
) -> None:
    while not _queue_complete(path, expected_run_dirs):
        _verify_locked_files(locked_files)
        _update_state(
            state_path,
            state,
            "waiting_for_nested_queue",
            waiting={
                "stage": stage,
                "queue_state_path": str(path),
                "checked_unix_time": time.time(),
            },
        )
        time.sleep(poll_seconds)
    state.pop("waiting", None)


def _convergence_report(
    protocol_path: Path,
    pairs: list[tuple[Path, Path]],
    output_path: Path,
) -> dict[str, Any]:
    protocol = _read_json(protocol_path)
    acceptance = protocol["acceptance"]
    report = compare_qe_settings(
        pairs,
        relative_energy_mev_atom_max=float(
            acceptance["relative_energy_mev_atom_max"]
        ),
        force_component_max_abs_change_ev_angstrom=float(
            acceptance["force_component_max_abs_change_ev_angstrom"]
        ),
        stress_component_max_abs_change_gpa=float(
            acceptance["stress_component_max_abs_change_gpa"]
        ),
    )
    report.update(
        protocol_path=str(protocol_path),
        protocol_sha256=sha256_file(protocol_path),
        implementation_path=str(Path(__file__).with_name("dft_convergence.py")),
        implementation_sha256=sha256_file(
            Path(__file__).with_name("dft_convergence.py")
        ),
    )
    write_convergence_report(output_path, report)
    return report


def _decision(
    protocol_path: Path,
    report_paths: list[Path],
    output_path: Path,
    *,
    stage: str,
) -> dict[str, Any]:
    result = choose_adjacent_setting(
        report_paths, stage=stage, protocol_path=protocol_path
    )
    _write_or_verify(output_path, result, label=f"{stage} decision")
    return result


def selected_scf_protocol(
    kpoints: Any, *, gamma_protocol: Path, k2_protocol: Path
) -> Path:
    if kpoints == "gamma":
        return gamma_protocol
    if kpoints == [2, 2, 2]:
        return k2_protocol
    raise ValueError(f"no preregistered SCF branch for k-points {kpoints!r}")


def build_runtime_mpi_protocol(
    selected_settings: dict[str, Any],
    configuration: dict[str, Any],
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
        label="frozen-final-setting",
        purpose="complete-grid MPI reproducibility at selected converged physics",
    )
    return {
        "schema_version": "1.0",
        "protocol_id": "llzto-qe-mpi-reproducibility-v1",
        "preregistration_rule": (
            "The rank grid, structures, and equivalence limits were frozen before "
            "execution. Numerical settings are copied mechanically from the passed "
            "SCF decision; timings cannot waive equivalence."
        ),
        "selection_is_model_blind": True,
        "selected_scf_decision_path": str(
            _repo_path(configuration["outputs"]["scf_decision"])
        ),
        "selected_scf_decision_sha256": sha256_file(
            _repo_path(configuration["outputs"]["scf_decision"])
        ),
        "execution_environment": configuration["execution_environment"],
        "physics": configuration["physics"],
        "calculations": [settings],
        "required_mpi_ranks": configuration["mpi"]["required_ranks"],
        "baseline_mpi_ranks": configuration["mpi"]["baseline_rank"],
        "structure_ids": list(configuration["convergence_structures"]),
        "acceptance": configuration["mpi"]["acceptance"],
    }


def _ensure_prepared(
    *,
    snapshot_manifest: Path,
    dft_protocol: Path,
    pseudo_manifest: Path,
    pseudo_dir: Path,
    qe_executable: Path,
    output_root: Path,
) -> None:
    campaign = output_root / "dft_campaign_manifest.json"
    if campaign.is_file():
        payload = _read_json(campaign)
        checks = {
            "snapshot": payload.get("snapshot_manifest_sha256")
            == sha256_file(snapshot_manifest),
            "protocol": payload.get("dft_protocol_sha256")
            == sha256_file(dft_protocol),
            "pseudo": payload.get("pseudopotential_manifest_sha256")
            == sha256_file(pseudo_manifest),
            "binary": payload.get("pw_executable_sha256")
            == sha256_file(qe_executable),
        }
        if not all(checks.values()):
            raise RuntimeError(f"prepared QE campaign provenance failed: {output_root}")
        return
    prepare_qe_inputs(
        snapshot_manifest,
        dft_protocol,
        pseudo_manifest,
        pseudo_dir=pseudo_dir,
        out_dir=output_root,
        qe_executable=qe_executable,
    )


def _run_nested_queue(
    run_dirs: list[Path],
    *,
    qe_prefix: Path,
    mpi_ranks: int,
    min_memory_gib: float,
    poll_seconds: float,
    state_path: Path,
) -> None:
    if _queue_complete(state_path, run_dirs):
        return
    run_queue(
        run_dirs,
        qe_prefix=qe_prefix,
        mpi_ranks=mpi_ranks,
        min_available_memory_gib=min_memory_gib,
        poll_seconds=poll_seconds,
        state_path=state_path,
    )
    if not _queue_complete(state_path, run_dirs):
        raise RuntimeError(f"nested QE queue did not complete: {state_path}")


def run_numerical_supervisor(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
) -> dict[str, Any]:
    source = Path(protocol_path).resolve()
    configuration = _read_json(source)
    if configuration.get("schema_version") != "1.0":
        raise ValueError("numerical supervisor protocol schema_version must be '1.0'")
    poll_seconds = float(configuration["resources"]["poll_seconds"])
    if not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 1 and 60")
    qe_prefix = Path(configuration["execution_environment"]["qe_prefix"]).resolve()
    qe_executable = qe_prefix / "bin/pw.x"
    snapshot_manifest = _repo_path(configuration["snapshot_manifest"]["path"])
    pseudo_manifest = _repo_path(configuration["pseudopotential_manifest"]["path"])
    pseudo_dir = Path(configuration["pseudopotential_manifest"]["local_directory"])
    kpoint_protocol = _repo_path(configuration["kpoint"]["protocol"])
    kpoint_protocol_payload = _read_json(kpoint_protocol)
    gamma_scf_protocol = _repo_path(configuration["scf"]["gamma_protocol"])
    k2_scf_protocol = _repo_path(configuration["scf"]["k2x2x2_protocol"])
    resource_evidence = _resource_evidence_hashes(kpoint_protocol_payload)
    assessment_value = configuration["kpoint"].get("extension_resource_assessment")
    assessment_path = _repo_path(assessment_value) if assessment_value else None
    if assessment_path is not None:
        resource_evidence[assessment_path] = configuration["kpoint"][
            "extension_resource_assessment_sha256"
        ]
    locked_paths = [
        source,
        snapshot_manifest,
        pseudo_manifest,
        kpoint_protocol,
        gamma_scf_protocol,
        k2_scf_protocol,
        Path(__file__).resolve(),
        Path(__file__).with_name("dft.py").resolve(),
        Path(__file__).with_name("dft_convergence.py").resolve(),
        Path(__file__).with_name("dft_decision.py").resolve(),
        Path(__file__).with_name("dft_mpi.py").resolve(),
        Path(__file__).with_name("qe_queue.py").resolve(),
        *resource_evidence,
    ]
    locked_files = [
        {"path": str(path), "sha256": sha256_file(path)} for path in locked_paths
    ]
    declared_hashes = {
        snapshot_manifest: configuration["snapshot_manifest"]["sha256"],
        pseudo_manifest: configuration["pseudopotential_manifest"]["sha256"],
        kpoint_protocol: configuration["kpoint"]["protocol_sha256"],
        gamma_scf_protocol: configuration["scf"]["gamma_protocol_sha256"],
        k2_scf_protocol: configuration["scf"]["k2x2x2_protocol_sha256"],
        qe_executable: configuration["execution_environment"][
            "pw_executable_sha256"
        ],
        **resource_evidence,
    }
    for path, expected in declared_hashes.items():
        if sha256_file(path) != expected:
            raise RuntimeError(f"declared numerical-supervisor hash mismatch: {path}")
    if assessment_path is not None:
        assessment = _read_json(assessment_path)
        unsigned_assessment = dict(assessment)
        assessment_fingerprint = unsigned_assessment.pop(
            "assessment_fingerprint", None
        )
        if not (
            assessment_fingerprint == fingerprint(unsigned_assessment)
            and assessment.get("assessment_pass") is True
            and assessment.get("kpoint_protocol_sha256")
            == sha256_file(kpoint_protocol)
        ):
            raise RuntimeError("invalid k-point extension resource assessment")

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
            raise RuntimeError(f"numerical supervisor configuration changed: {output_state}")
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
        _verify_locked_files(locked_files)
        structures = configuration["convergence_structures"]
        k2_dirs = [
            _repo_path(configuration["kpoint"]["k2x2x2_runs"][name])
            for name in structures
        ]
        current_kpoint_queue = _repo_path(
            configuration["kpoint"]["current_queue_state"]
        )
        _wait_for_queue(
            current_kpoint_queue,
            k2_dirs,
            state_path=output_state,
            state=state,
            stage="kpoint-gamma-vs-2x2x2",
            poll_seconds=poll_seconds,
            locked_files=locked_files,
        )
        kpoint_report_paths = [
            _repo_path(configuration["outputs"]["kpoint_gamma_2x2x2_report"])
        ]
        gamma_dirs = [
            _repo_path(configuration["kpoint"]["gamma_runs"][name])
            for name in structures
        ]
        first_kpoint = _convergence_report(
            kpoint_protocol,
            list(zip(gamma_dirs, k2_dirs)),
            kpoint_report_paths[0],
        )
        state["stages"]["kpoint_gamma_2x2x2"] = {
            "status": "pass" if first_kpoint["numerically_converged"] else "fail",
            "report_path": str(kpoint_report_paths[0]),
            "report_sha256": sha256_file(kpoint_report_paths[0]),
        }
        if not first_kpoint["numerically_converged"]:
            extension_root = _repo_path(configuration["kpoint"]["extension_root"])
            _ensure_prepared(
                snapshot_manifest=snapshot_manifest,
                dft_protocol=kpoint_protocol,
                pseudo_manifest=pseudo_manifest,
                pseudo_dir=pseudo_dir,
                qe_executable=qe_executable,
                output_root=extension_root,
            )
            k3_label = configuration["kpoint"]["extension_label"]
            k3_dirs = [extension_root / f"{name}--{k3_label}" for name in structures]
            matching_calculations = [
                row
                for row in kpoint_protocol_payload["calculations"]
                if row.get("label") == k3_label
            ]
            if len(matching_calculations) != 1:
                raise RuntimeError("k-point extension calculation is not unique")
            expected_disk_io = matching_calculations[0].get("disk_io", "low")
            for run_dir in k3_dirs:
                run_manifest = _read_json(run_dir / "run_manifest.json")
                input_path = run_dir / "pw.in"
                if not (
                    run_manifest.get("settings", {}).get("disk_io", "low")
                    == expected_disk_io
                    and f"disk_io = '{expected_disk_io}'"
                    in input_path.read_text(encoding="utf-8")
                    and run_manifest.get("input_sha256") == sha256_file(input_path)
                ):
                    raise RuntimeError(
                        f"k-point extension I/O provenance failed: {run_dir}"
                    )
            release_path = _repo_path(
                configuration["kpoint"]["extension_resource_release"]
            )
            while not release_path.is_file():
                _verify_locked_files(locked_files)
                _update_state(
                    output_state,
                    state,
                    "waiting_for_kpoint_extension_resource_release",
                    waiting={
                        "stage": "kpoint-2x2x2-vs-3x3x3",
                        "release_path": str(release_path),
                        "reason": configuration["kpoint"][
                            "extension_resource_reason"
                        ],
                        "checked_unix_time": time.time(),
                    },
                )
                time.sleep(poll_seconds)
            release = _read_json(release_path)
            unsigned = dict(release)
            stored = unsigned.pop("gate_fingerprint", None)
            assessment_release_valid = assessment_path is None or (
                Path(release.get("resource_assessment_path", "")).resolve()
                == assessment_path
                and release.get("resource_assessment_sha256")
                == sha256_file(assessment_path)
            )
            max_estimated_ram = configuration["resources"].get(
                "kpoint_extension_max_estimated_total_ram_gb"
            )
            estimated_ram_valid = max_estimated_ram is None or float(
                release.get("qe_estimated_total_dynamical_ram_gb", float("inf"))
            ) <= float(max_estimated_ram)
            if not (
                release.get("gate_id") == "qe-kpoint-3x3x3-resource-release"
                and release.get("status") == "pass"
                and release.get("kpoint_protocol_sha256")
                == sha256_file(kpoint_protocol)
                and Path(release.get("trigger_report_path", "")).resolve()
                == kpoint_report_paths[0]
                and release.get("trigger_report_sha256")
                == sha256_file(kpoint_report_paths[0])
                and float(release.get("assessed_available_memory_gib", 0))
                >= float(
                    configuration["resources"][
                        "kpoint_extension_min_memory_gib"
                    ]
                )
                and assessment_release_valid
                and estimated_ram_valid
                and release.get("maximum_concurrent_qe_jobs", 1) == 1
                and release.get("swap_counted_as_capacity", False) is False
                and stored == fingerprint(unsigned)
            ):
                raise RuntimeError("invalid 3x3x3 resource-release gate")
            extension_queue = _repo_path(
                configuration["kpoint"]["extension_queue_state"]
            )
            _run_nested_queue(
                k3_dirs,
                qe_prefix=qe_prefix,
                mpi_ranks=int(configuration["resources"]["production_mpi_ranks"]),
                min_memory_gib=float(
                    configuration["resources"]["kpoint_extension_min_memory_gib"]
                ),
                poll_seconds=poll_seconds,
                state_path=extension_queue,
            )
            second_path = _repo_path(
                configuration["outputs"]["kpoint_2x2x2_3x3x3_report"]
            )
            second_kpoint = _convergence_report(
                kpoint_protocol, list(zip(k2_dirs, k3_dirs)), second_path
            )
            kpoint_report_paths.append(second_path)
            state["stages"]["kpoint_2x2x2_3x3x3"] = {
                "status": "pass"
                if second_kpoint["numerically_converged"]
                else "fail",
                "report_path": str(second_path),
                "report_sha256": sha256_file(second_path),
            }
        kpoint_decision_path = _repo_path(configuration["outputs"]["kpoint_decision"])
        kpoint_decision = _decision(
            kpoint_protocol,
            kpoint_report_paths,
            kpoint_decision_path,
            stage="kpoint",
        )
        state["stages"]["kpoint_decision"] = {
            "status": kpoint_decision["decision_status"],
            "path": str(kpoint_decision_path),
            "sha256": sha256_file(kpoint_decision_path),
        }
        if not kpoint_decision["can_continue"]:
            _update_state(
                output_state,
                state,
                "blocked_no_converged_kpoint",
                blocker={
                    "required_action": (
                        "Use a larger-memory QE host and freeze the next denser "
                        "comparison without changing thresholds."
                    )
                },
            )
            return state

        _verify_locked_files(locked_files)
        scf_protocol = selected_scf_protocol(
            kpoint_decision["selected_settings"]["kpoints"],
            gamma_protocol=gamma_scf_protocol,
            k2_protocol=k2_scf_protocol,
        )
        scf = _read_json(scf_protocol)
        scf_root = _repo_path(configuration["scf"]["output_root"])
        _ensure_prepared(
            snapshot_manifest=snapshot_manifest,
            dft_protocol=scf_protocol,
            pseudo_manifest=pseudo_manifest,
            pseudo_dir=pseudo_dir,
            qe_executable=qe_executable,
            output_root=scf_root,
        )
        baseline_dirs = [
            _repo_path(scf["baseline_runs"][name]) for name in structures
        ]
        calculation_labels = [row["label"] for row in scf["calculations"]]
        scf_report_paths: list[Path] = []
        previous_dirs = baseline_dirs
        for index, label in enumerate(calculation_labels):
            upper_dirs = [scf_root / f"{name}--{label}" for name in structures]
            queue_path = _repo_path(configuration["scf"]["queue_states"][index])
            _update_state(
                output_state,
                state,
                "running_scf_queue",
                current={"comparison_index": index, "queue_state_path": str(queue_path)},
            )
            _run_nested_queue(
                upper_dirs,
                qe_prefix=qe_prefix,
                mpi_ranks=int(configuration["resources"]["production_mpi_ranks"]),
                min_memory_gib=float(
                    configuration["resources"]["standard_min_memory_gib"]
                ),
                poll_seconds=poll_seconds,
                state_path=queue_path,
            )
            report_path = _repo_path(configuration["scf"]["report_paths"][index])
            report = _convergence_report(
                scf_protocol, list(zip(previous_dirs, upper_dirs)), report_path
            )
            scf_report_paths.append(report_path)
            state["stages"][f"scf_comparison_{index}"] = {
                "status": "pass" if report["numerically_converged"] else "fail",
                "path": str(report_path),
                "sha256": sha256_file(report_path),
            }
            if report["numerically_converged"]:
                break
            previous_dirs = upper_dirs
        scf_decision_path = _repo_path(configuration["outputs"]["scf_decision"])
        scf_decision = _decision(
            scf_protocol, scf_report_paths, scf_decision_path, stage="scf"
        )
        state["stages"]["scf_decision"] = {
            "status": scf_decision["decision_status"],
            "path": str(scf_decision_path),
            "sha256": sha256_file(scf_decision_path),
        }
        if not scf_decision["can_continue"]:
            _update_state(
                output_state,
                state,
                "blocked_no_converged_scf_threshold",
                blocker={
                    "required_action": (
                        "Freeze a stricter SCF comparison without changing limits."
                    )
                },
            )
            return state

        _verify_locked_files(locked_files)
        mpi_root = _repo_path(configuration["mpi"]["output_root"])
        mpi_root.mkdir(parents=True, exist_ok=True)
        mpi_protocol_path = _repo_path(configuration["mpi"]["runtime_protocol"])
        mpi_protocol = build_runtime_mpi_protocol(
            scf_decision["selected_settings"], configuration
        )
        _write_or_verify(mpi_protocol_path, mpi_protocol, label="runtime MPI protocol")
        rank_runs: list[tuple[int, str, Path]] = []
        queue_entries: list[tuple[int, Path]] = []
        mpi_label = mpi_protocol["calculations"][0]["label"]
        for rank_value in mpi_protocol["required_mpi_ranks"]:
            rank = int(rank_value)
            rank_root = mpi_root / f"rank{rank}"
            _ensure_prepared(
                snapshot_manifest=snapshot_manifest,
                dft_protocol=mpi_protocol_path,
                pseudo_manifest=pseudo_manifest,
                pseudo_dir=pseudo_dir,
                qe_executable=qe_executable,
                output_root=rank_root,
            )
            run_dirs = [
                rank_root / f"{name}--{mpi_label}" for name in structures
            ]
            rank_queue = _repo_path(
                configuration["mpi"]["queue_state_pattern"].format(rank=rank)
            )
            _update_state(
                output_state,
                state,
                "running_mpi_reproducibility",
                current={"mpi_ranks": rank, "queue_state_path": str(rank_queue)},
            )
            _run_nested_queue(
                run_dirs,
                qe_prefix=qe_prefix,
                mpi_ranks=rank,
                min_memory_gib=float(
                    configuration["resources"]["standard_min_memory_gib"]
                ),
                poll_seconds=poll_seconds,
                state_path=rank_queue,
            )
            queue_entries.append((rank, rank_queue))
            rank_runs.extend(
                (rank, structure_id, directory)
                for structure_id, directory in zip(structures, run_dirs)
            )
        mpi_report = build_mpi_report(
            mpi_protocol_path, rank_runs, queue_entries
        )
        mpi_report_path = _repo_path(configuration["outputs"]["mpi_report"])
        _write_or_verify(mpi_report_path, mpi_report, label="MPI report")
        state["stages"]["mpi_reproducibility"] = {
            "status": "pass"
            if mpi_report["mpi_equivalence_gate_pass"]
            else "fail",
            "path": str(mpi_report_path),
            "sha256": sha256_file(mpi_report_path),
        }
        if not mpi_report["mpi_equivalence_gate_pass"]:
            _update_state(
                output_state,
                state,
                "blocked_mpi_nonequivalence",
                blocker={
                    "required_action": (
                        "Preserve the failed rank result and use an equivalent rank "
                        "configuration; timing cannot waive this gate."
                    )
                },
            )
            return state
        state.pop("current", None)
        state.pop("waiting", None)
        _update_state(
            output_state,
            state,
            "complete",
            selected_settings=scf_decision["selected_settings"],
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
    result = run_numerical_supervisor(args.protocol, state_path=args.state)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
