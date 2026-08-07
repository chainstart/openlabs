"""Persistent end-to-end LLZTO analysis, publication, and audit supervisor."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .attestation import (
    build_environment_attestation,
    run_clean_regeneration_attestation,
    run_test_attestation,
)
from .evidence_audit import build_evidence_audit
from .manuscript import build_manuscript_package
from .mechanism_queue import acquire_analysis_lock, release_analysis_lock
from .mechanism_transport import build_mechanism_transport_report
from .provenance import (
    atomic_write_json,
    fingerprint,
    git_state,
    sha256_file,
)
from .publication import build_publication_package
from .q1_readiness import build_q1_readiness_assessment
from .report import build_campaign_report
from .transport_sensitivity import build_sensitivity_report
from .transport_statistics import build_hierarchical_transport_report
from .validation import (
    build_hierarchical_validation_report,
    load_benchmarks,
)
from .velocity_statistics import build_velocity_report


_ROOT = Path(__file__).resolve().parents[2]
_TERMINAL_UPSTREAM_PREFIXES = ("failed", "blocked")
_COMPLETE_JOB_STATES = {"complete", "already_complete"}


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


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _verify_locked_files(records: list[dict[str, str]]) -> None:
    for record in records:
        path = Path(record["path"]).resolve()
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"final-supervisor locked file changed: {path}")


def inspect_upstream_state(
    specification: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Validate one mutable queue state without treating waiting as failure."""
    state_id = str(specification["state_id"])
    status = str(payload.get("status", "missing_status"))
    config = payload.get("config")
    if not isinstance(config, dict):
        raise RuntimeError(f"upstream {state_id} has no configuration")
    expected_protocol = specification.get("expected_protocol_sha256")
    observed_protocol = config.get("protocol_sha256") or config.get(
        "association_protocol_sha256"
    )
    if expected_protocol is not None and observed_protocol != expected_protocol:
        raise RuntimeError(f"upstream {state_id} protocol hash mismatch")

    expected_runs = specification.get("expected_run_ids")
    if expected_runs is not None and set(config.get("run_ids", [])) != set(
        expected_runs
    ):
        raise RuntimeError(f"upstream {state_id} run grid mismatch")

    expected_jobs = specification.get("expected_job_ids")
    jobs = payload.get("jobs", {})
    if not isinstance(jobs, dict):
        raise RuntimeError(f"upstream {state_id} jobs are not an object")
    expected_complete_jobs = expected_jobs if expected_jobs is not None else expected_runs
    if status == "complete" and expected_complete_jobs is not None:
        if set(jobs) != set(expected_complete_jobs):
            raise RuntimeError(f"upstream {state_id} completed job grid mismatch")
        invalid = {
            job_id: row.get("status")
            for job_id, row in jobs.items()
            if not isinstance(row, dict)
            or row.get("status") not in _COMPLETE_JOB_STATES
        }
        if invalid:
            raise RuntimeError(
                f"upstream {state_id} has non-complete jobs: {invalid}"
            )
    return {
        "state_id": state_id,
        "status": status,
        "complete": status == "complete",
        "terminal_block": status.startswith(_TERMINAL_UPSTREAM_PREFIXES),
        "job_count": len(jobs),
    }


def inspect_upstream_states(
    specifications: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    for specification in specifications:
        path = _repo_path(specification["path"])
        if not path.is_file():
            rows.append(
                {
                    "state_id": specification["state_id"],
                    "path": str(path),
                    "status": "missing",
                    "complete": False,
                    "terminal_block": False,
                    "job_count": 0,
                }
            )
            continue
        row = inspect_upstream_state(specification, _read_json(path))
        row.update(path=str(path), sha256=sha256_file(path))
        rows.append(row)
    return {
        "all_complete": all(row["complete"] for row in rows),
        "terminal_blocks": [row for row in rows if row["terminal_block"]],
        "states": rows,
    }


def _wait_for_upstreams(
    configuration: dict[str, Any],
    *,
    state_path: Path,
    state: dict[str, Any],
    locked_files: list[dict[str, str]],
) -> dict[str, Any]:
    poll_seconds = float(configuration["resources"]["poll_seconds"])
    while True:
        _verify_locked_files(locked_files)
        inspection = inspect_upstream_states(configuration["upstream_states"])
        if inspection["all_complete"]:
            state.pop("waiting", None)
            return inspection
        status = (
            "blocked_by_upstream"
            if inspection["terminal_blocks"]
            else "waiting_for_upstream_queues"
        )
        _update_state(
            state_path,
            state,
            status,
            waiting={
                "checked_unix_time": time.time(),
                **inspection,
            },
        )
        time.sleep(poll_seconds)


def _ensure_fingerprinted_output(
    path: Path,
    *,
    fingerprint_field: str,
    label: str,
    builder: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if path.is_file():
        payload = _read_json(path)
    else:
        payload = builder()
        if not path.is_file():
            atomic_write_json(path, payload)
    _verify_fingerprint(payload, fingerprint_field, label)
    if _read_json(path) != payload:
        raise RuntimeError(f"{label} builder and stored output differ: {path}")
    return payload


def _stage_record(
    path: Path,
    payload: dict[str, Any],
    *,
    gate_pass: bool,
) -> dict[str, Any]:
    return {
        "status": "pass" if gate_pass else "block",
        "path": str(path),
        "sha256": sha256_file(path),
        "gate_pass": bool(gate_pass),
        "report_kind": payload.get("report_kind")
        or payload.get("manifest_kind")
        or payload.get("attestation_kind"),
    }


def _parallel_analysis_jobs(
    configuration: dict[str, Any],
) -> dict[str, tuple[Path, dict[str, Any], bool, str]]:
    analysis = configuration["analysis"]
    outputs = configuration["outputs"]
    hierarchical_protocol = _repo_path(analysis["hierarchical_protocol"])
    formal_root = _repo_path(analysis["formal_campaign_root"])
    mechanism_root = _repo_path(analysis["mechanism_root"])
    mechanism_protocol = _repo_path(analysis["mechanism_association_protocol"])
    jobs: dict[
        str,
        tuple[
            Path,
            str,
            Callable[[], dict[str, Any]],
            Callable[[dict[str, Any]], bool],
            str,
        ],
    ] = {
        "hierarchical_transport": (
            _repo_path(outputs["hierarchical_transport"]),
            "report_fingerprint",
            lambda: build_hierarchical_transport_report(
                formal_root, hierarchical_protocol
            ),
            lambda row: row.get("hierarchical_gate_pass") is True,
            configuration["failure_rules"]["unresolved_transport"],
        ),
        "nested_velocity": (
            _repo_path(outputs["nested_velocity"]),
            "report_fingerprint",
            lambda: build_velocity_report(hierarchical_protocol),
            lambda row: row.get("result", {}).get("nested_velocity_gate_pass")
            is True,
            configuration["failure_rules"]["unresolved_transport"],
        ),
        "transport_sensitivity": (
            _repo_path(outputs["transport_sensitivity"]),
            "report_fingerprint",
            lambda: build_sensitivity_report(hierarchical_protocol),
            lambda row: row.get("sensitivity_gate_pass") is True,
            configuration["failure_rules"]["sensitivity_failure"],
        ),
        "mechanism_association": (
            _repo_path(outputs["mechanism_association"]),
            "report_fingerprint",
            lambda: build_mechanism_transport_report(
                formal_root, mechanism_root, mechanism_protocol
            ),
            lambda row: row.get("input_gate_pass") is True
            and row.get("analysis", {}).get("grid_gate_pass") is True
            and len(row.get("analysis_records", [])) == 25,
            configuration["failure_rules"]["analysis_failure"],
        ),
    }

    def run_one(
        name: str,
    ) -> tuple[str, Path, dict[str, Any], bool, str]:
        path, fingerprint_field, builder, validator, action = jobs[name]
        payload = _ensure_fingerprinted_output(
            path,
            fingerprint_field=fingerprint_field,
            label=name,
            builder=builder,
        )
        return name, path, payload, bool(validator(payload)), action

    results: dict[str, tuple[Path, dict[str, Any], bool, str]] = {}
    workers = int(configuration["resources"]["parallel_analysis_workers"])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, name): name for name in jobs}
        for future in as_completed(futures):
            name, path, payload, passed, action = future.result()
            results[name] = (path, payload, passed, action)
    return results


def _verify_protocol_declarations(configuration: dict[str, Any]) -> list[Path]:
    paths = []
    for record in configuration["declared_files"]:
        path = _repo_path(record["path"])
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"declared final-supervisor hash mismatch: {path}")
        paths.append(path)
    return paths


def run_final_supervisor(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
) -> dict[str, Any]:
    source = Path(protocol_path).resolve()
    configuration = _read_json(source)
    if configuration.get("schema_version") != "1.0":
        raise ValueError("final supervisor protocol schema_version must be '1.0'")
    poll_seconds = float(configuration["resources"]["poll_seconds"])
    workers = int(configuration["resources"]["parallel_analysis_workers"])
    if not 1 <= poll_seconds <= 60 or not 1 <= workers <= 4:
        raise ValueError("final supervisor resource settings are outside safe limits")

    declared_paths = _verify_protocol_declarations(configuration)
    audit_protocol = _repo_path(
        configuration["publication"]["evidence_audit_protocol"]
    )
    implementation_paths = [
        Path(__file__).resolve(),
        Path(__file__).with_name("attestation.py").resolve(),
        Path(__file__).with_name("evidence_audit.py").resolve(),
        Path(__file__).with_name("manuscript.py").resolve(),
        Path(__file__).with_name("mechanism_transport.py").resolve(),
        Path(__file__).with_name("provenance.py").resolve(),
        Path(__file__).with_name("publication.py").resolve(),
        Path(__file__).with_name("q1_readiness.py").resolve(),
        Path(__file__).with_name("report.py").resolve(),
        Path(__file__).with_name("transport_sensitivity.py").resolve(),
        Path(__file__).with_name("transport_statistics.py").resolve(),
        Path(__file__).with_name("validation.py").resolve(),
        Path(__file__).with_name("velocity_statistics.py").resolve(),
    ]
    locked_paths = [source, audit_protocol, *declared_paths, *implementation_paths]
    unique_locked = {str(path.resolve()): path.resolve() for path in locked_paths}
    locked_files = [
        {"path": key, "sha256": sha256_file(path)}
        for key, path in sorted(unique_locked.items())
    ]
    output_state = Path(state_path).resolve()
    config_record = {
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "audit_protocol_path": str(audit_protocol),
        "audit_protocol_sha256": sha256_file(audit_protocol),
        "locked_files": locked_files,
    }
    queue_fingerprint = fingerprint(config_record)
    if output_state.is_file():
        state = _read_json(output_state)
        if state.get("queue_fingerprint") != queue_fingerprint:
            raise RuntimeError(f"final supervisor configuration changed: {output_state}")
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
        upstream = _wait_for_upstreams(
            configuration,
            state_path=output_state,
            state=state,
            locked_files=locked_files,
        )
        state["stages"]["upstream_queues"] = {
            "status": "complete",
            "states": upstream["states"],
        }

        lock_path = _repo_path(configuration["resources"]["cpu_lock"])
        lock_handle = None
        while lock_handle is None:
            _verify_locked_files(locked_files)
            lock_handle = acquire_analysis_lock(lock_path)
            if lock_handle is None:
                _update_state(
                    output_state,
                    state,
                    "waiting_for_final_analysis_cpu_lock",
                    waiting={
                        "cpu_lock_path": str(lock_path),
                        "checked_unix_time": time.time(),
                    },
                )
                time.sleep(poll_seconds)
        try:
            _update_state(output_state, state, "building_campaign_report")
            campaign_root = _repo_path(
                configuration["analysis"]["formal_campaign_root"]
            )
            campaign_report_path = _repo_path(
                configuration["outputs"]["campaign_report"]
            )
            campaign_report = build_campaign_report(campaign_root)
            if (
                not campaign_report_path.is_file()
                or _read_json(campaign_report_path) != campaign_report
            ):
                atomic_write_json(campaign_report_path, campaign_report)
            campaign_gate = campaign_report.get("numerical_gate", {}).get(
                "all_energy_drift_checks_pass"
            ) is True
            state["stages"]["campaign_report"] = _stage_record(
                campaign_report_path, campaign_report, gate_pass=campaign_gate
            )
            if not campaign_gate:
                _update_state(
                    output_state,
                    state,
                    "blocked_scientific_gate",
                    blockers=[
                        {
                            "stage": "campaign_report",
                            "required_action": configuration["failure_rules"][
                                "analysis_failure"
                            ],
                        }
                    ],
                )
                return state

            _update_state(output_state, state, "running_parallel_formal_analyses")
            analysis_results = _parallel_analysis_jobs(configuration)
            blockers = []
            for name, (path, payload, passed, action) in sorted(
                analysis_results.items()
            ):
                state["stages"][name] = _stage_record(
                    path, payload, gate_pass=passed
                )
                if not passed:
                    blockers.append(
                        {
                            "stage": name,
                            "path": str(path),
                            "required_action": action,
                        }
                    )
            if blockers:
                _update_state(
                    output_state,
                    state,
                    "blocked_scientific_gate",
                    blockers=blockers,
                )
                return state

            outputs = configuration["outputs"]
            publication = configuration["publication"]
            hierarchical_path = _repo_path(outputs["hierarchical_transport"])
            benchmark_path = _repo_path(
                configuration["analysis"]["experimental_benchmarks"]
            )
            experimental_path = _repo_path(outputs["experimental_validation"])
            _update_state(output_state, state, "building_experimental_validation")

            def build_experiment() -> dict[str, Any]:
                hierarchical = _read_json(hierarchical_path)
                benchmarks = load_benchmarks(benchmark_path)
                return build_hierarchical_validation_report(
                    hierarchical,
                    benchmarks,
                    hierarchical_report_path=hierarchical_path,
                    benchmark_path=benchmark_path,
                )

            experiment = _ensure_fingerprinted_output(
                experimental_path,
                fingerprint_field="report_fingerprint",
                label="experimental validation",
                builder=build_experiment,
            )
            experiment_gate = bool(
                experiment.get("n_eligible_measurements") == 9
                and experiment.get("n_evaluated") == 9
                and experiment.get("n_blocked") == 0
            )
            state["stages"]["experimental_validation"] = _stage_record(
                experimental_path, experiment, gate_pass=experiment_gate
            )
            if not experiment_gate:
                _update_state(
                    output_state,
                    state,
                    "blocked_scientific_gate",
                    blockers=[
                        {
                            "stage": "experimental_validation",
                            "path": str(experimental_path),
                            "required_action": configuration["failure_rules"][
                                "unresolved_transport"
                            ],
                        }
                    ],
                )
                return state

            publication_protocol = _repo_path(publication["protocol"])
            publication_manifest_path = _repo_path(outputs["publication_manifest"])
            _update_state(output_state, state, "building_publication_package")
            artifact_manifest = _ensure_fingerprinted_output(
                publication_manifest_path,
                fingerprint_field="manifest_fingerprint",
                label="publication package",
                builder=lambda: build_publication_package(publication_protocol),
            )
            publication_gate = artifact_manifest.get("manifest_gate_pass") is True
            state["stages"]["publication_package"] = _stage_record(
                publication_manifest_path,
                artifact_manifest,
                gate_pass=publication_gate,
            )
            if not publication_gate:
                raise RuntimeError("publication artifact manifest did not pass")

            manuscript_protocol = _repo_path(publication["manuscript_protocol"])
            manuscript_manifest_path = _repo_path(outputs["manuscript_manifest"])
            _update_state(output_state, state, "building_manuscript_package")
            manuscript_manifest = _ensure_fingerprinted_output(
                manuscript_manifest_path,
                fingerprint_field="manifest_fingerprint",
                label="manuscript package",
                builder=lambda: build_manuscript_package(manuscript_protocol),
            )
            manuscript_gate = manuscript_manifest.get("manuscript_gate_pass") is True
            state["stages"]["manuscript_package"] = _stage_record(
                manuscript_manifest_path,
                manuscript_manifest,
                gate_pass=manuscript_gate,
            )
            if not manuscript_gate:
                raise RuntimeError("manuscript manifest did not pass")

            current_git = git_state(_ROOT)
            test_path = _repo_path(outputs["test_attestation"])
            _update_state(output_state, state, "running_test_attestation")
            test_attestation = _ensure_fingerprinted_output(
                test_path,
                fingerprint_field="attestation_fingerprint",
                label="test attestation",
                builder=lambda: run_test_attestation(test_path),
            )
            test_gate = bool(
                test_attestation.get("tests_failed") == 0
                and test_attestation.get("git_dirty") is False
                and test_attestation.get("git_commit") == current_git["commit"]
            )
            state["stages"]["test_attestation"] = _stage_record(
                test_path, test_attestation, gate_pass=test_gate
            )
            if not test_gate:
                raise RuntimeError("test attestation is not for the final clean commit")

            environment_path = _repo_path(outputs["environment_attestation"])
            qe_manifest = _repo_path(publication["qe_environment_manifest"])
            formal_manifest = _repo_path(publication["formal_run_manifest"])
            _update_state(output_state, state, "building_environment_attestation")
            environment = _ensure_fingerprinted_output(
                environment_path,
                fingerprint_field="attestation_fingerprint",
                label="environment attestation",
                builder=lambda: build_environment_attestation(
                    audit_protocol,
                    qe_manifest_path=qe_manifest,
                    formal_run_manifest_path=formal_manifest,
                    out_path=environment_path,
                ),
            )
            environment_gate = bool(
                environment.get("environment_gate_pass") is True
                and environment.get("git_state", {}).get("dirty") is False
                and environment.get("git_state", {}).get("commit")
                == current_git["commit"]
            )
            state["stages"]["environment_attestation"] = _stage_record(
                environment_path, environment, gate_pass=environment_gate
            )
            if not environment_gate:
                raise RuntimeError("environment attestation did not pass cleanly")

            regeneration_path = _repo_path(
                outputs["clean_regeneration_attestation"]
            )
            _update_state(output_state, state, "running_clean_regeneration")
            regeneration = _ensure_fingerprinted_output(
                regeneration_path,
                fingerprint_field="attestation_fingerprint",
                label="clean regeneration attestation",
                builder=lambda: run_clean_regeneration_attestation(
                    publication_protocol,
                    publication_manifest_path,
                    manuscript_protocol_path=manuscript_protocol,
                    manuscript_manifest_path=manuscript_manifest_path,
                    out_path=regeneration_path,
                ),
            )
            regeneration_gate = bool(
                regeneration.get("all_commands_exit_zero") is True
                and regeneration.get("all_declared_artifact_hashes_verified")
                is True
                and regeneration.get("comparison", {}).get("all_hashes_match")
                is True
                and regeneration.get("manuscript_comparison", {}).get(
                    "all_hashes_match"
                )
                is True
            )
            state["stages"]["clean_regeneration"] = _stage_record(
                regeneration_path, regeneration, gate_pass=regeneration_gate
            )
            if not regeneration_gate:
                raise RuntimeError("clean regeneration attestation did not pass")

            audit_path = _repo_path(outputs["evidence_audit"])
            _update_state(output_state, state, "running_final_evidence_audit")
            evidence_audit = _ensure_fingerprinted_output(
                audit_path,
                fingerprint_field="report_fingerprint",
                label="final evidence audit",
                builder=lambda: build_evidence_audit(audit_protocol),
            )
            audit_gate = bool(
                evidence_audit.get("evidence_chain_complete") is True
                and evidence_audit.get(
                    "ready_for_final_qualitative_q1_assessment"
                )
                is True
                and evidence_audit.get("blockers") == []
            )
            state["stages"]["evidence_audit"] = _stage_record(
                audit_path, evidence_audit, gate_pass=audit_gate
            )
            if not audit_gate:
                _update_state(
                    output_state,
                    state,
                    "blocked_final_evidence_audit",
                    blockers=evidence_audit.get("blockers", []),
                )
                return state

            readiness_protocol = _repo_path(publication["q1_readiness_protocol"])
            readiness_path = _repo_path(outputs["q1_readiness"])
            _update_state(output_state, state, "building_q1_readiness_dossier")
            readiness = _ensure_fingerprinted_output(
                readiness_path,
                fingerprint_field="report_fingerprint",
                label="Q1-readiness dossier",
                builder=lambda: build_q1_readiness_assessment(readiness_protocol),
            )
            readiness_gate = bool(
                readiness.get("final_q1_level_judgment_authorized") is True
                and readiness.get("final_q1_level_judgment_completed") is False
            )
            state["stages"]["q1_readiness"] = _stage_record(
                readiness_path, readiness, gate_pass=readiness_gate
            )
            if not readiness_gate:
                raise RuntimeError("Q1-readiness dossier did not authorize review")
        finally:
            release_analysis_lock(lock_handle)

        state.pop("waiting", None)
        state.pop("blockers", None)
        _update_state(
            output_state,
            state,
            "complete",
            completed_unix_time=time.time(),
            final_disposition={
                "evidence_chain_complete": True,
                "q1_readiness_path": str(readiness_path),
                "q1_readiness_sha256": sha256_file(readiness_path),
                "external_qualitative_assessment_required": True,
            },
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
    result = run_final_supervisor(args.protocol, state_path=args.state)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
