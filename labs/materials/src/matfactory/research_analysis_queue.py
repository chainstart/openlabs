"""Outcome-aware branch routing and complete LLZTO research analysis."""

from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .ensemble_sensitivity import build_ensemble_sensitivity_report
from .final_queue import inspect_upstream_state
from .haven_validation import build_haven_validation_report
from .mechanism_queue import acquire_analysis_lock, release_analysis_lock
from .mechanism_temperature_robustness import (
    build_temperature_robustness_report,
)
from .mechanism_transport import build_mechanism_transport_report
from .provenance import atomic_write_json, fingerprint, sha256_file
from .report import build_campaign_report
from .transport_sensitivity import build_sensitivity_report
from .transport_statistics import build_hierarchical_transport_report
from .validation import build_hierarchical_validation_report, load_benchmarks
from .velocity_statistics import build_velocity_report


_ROOT = Path(__file__).resolve().parents[2]
_TERMINAL_PREFIXES = ("failed", "blocked")


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


def _write_or_verify(
    path: Path,
    payload: dict[str, Any],
    *,
    label: str,
    fingerprint_field: str | None = None,
) -> dict[str, Any]:
    if fingerprint_field is not None:
        _verify_fingerprint(payload, fingerprint_field, label)
    if path.exists():
        existing = _read_json(path)
        if existing != payload:
            raise RuntimeError(f"stored {label} differs from deterministic rebuild: {path}")
        if fingerprint_field is not None:
            _verify_fingerprint(existing, fingerprint_field, label)
        return existing
    atomic_write_json(path, payload)
    return payload


def _sensitivity_analysis_complete(report: dict[str, Any]) -> bool:
    """Separate estimability from a scientifically negative equivalence result."""
    estimator_names = {"tracer", "collective", "collective_to_tracer_ratio"}

    def comparison_complete(comparison: Any) -> bool:
        if not isinstance(comparison, dict):
            return False
        estimators = comparison.get("estimators")
        return bool(
            comparison.get("comparison_gate_pass") is True
            and isinstance(estimators, dict)
            and set(estimators) == estimator_names
            and all(
                row.get("analysis_gate_pass") is True
                for row in estimators.values()
                if isinstance(row, dict)
            )
            and all(isinstance(row, dict) for row in estimators.values())
        )

    finite_size = report.get("finite_size")
    fixed_volume = report.get("fixed_experimental_volume")
    npt_volume = report.get("npt_volume")
    if not (
        comparison_complete(finite_size)
        and comparison_complete(fixed_volume)
        and isinstance(npt_volume, dict)
    ):
        return False
    by_temperature = npt_volume.get("by_temperature")
    activation = npt_volume.get("activation_energy_difference")
    return bool(
        isinstance(by_temperature, list)
        and len(by_temperature) == 5
        and all(comparison_complete(row) for row in by_temperature)
        and isinstance(activation, dict)
        and set(activation) == {"tracer", "collective"}
        and all(
            isinstance(row, dict) and row.get("analysis_gate_pass") is True
            for row in activation.values()
        )
    )


def validate_research_analysis_protocol(
    path: Path | str,
) -> tuple[dict[str, Any], Path]:
    """Verify the frozen router and every static protocol/source hash."""
    source = Path(path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("research analysis protocol schema_version must be '1.0'")
    if protocol.get("protocol_id") != "llzto-research-analysis-supervisor-v2":
        raise ValueError("unexpected research analysis protocol id")
    routing = protocol["routing"]
    declared = [
        (
            routing["universal_domain_protocol"],
            routing["universal_domain_protocol_sha256"],
        ),
        (
            routing["fine_tuning_protocol"],
            routing["fine_tuning_protocol_sha256"],
        ),
        (
            routing["fine_rerun_protocol"],
            routing["fine_rerun_protocol_sha256"],
        ),
    ]
    declared.extend(
        (record["path"], record["sha256"])
        for record in protocol["source_protocols"].values()
    )
    for value, expected in declared:
        candidate = _repo_path(value)
        if sha256_file(candidate) != expected:
            raise RuntimeError(f"research analysis declared hash mismatch: {candidate}")
    if set(protocol["branches"]) != {"universal", "finetuned"}:
        raise ValueError("research analysis must declare exactly two model branches")
    output_names = set(protocol["outputs"])
    expected_outputs = {
        "root_template",
        "protocol_root_template",
        "campaign_report",
        "hierarchical",
        "nested_velocity",
        "transport_sensitivity",
        "mechanism_association",
        "experimental_validation",
        "ensemble",
        "mechanism_temperature",
        "haven",
        "analysis_manifest",
    }
    if output_names != expected_outputs:
        raise ValueError("research analysis output inventory changed")
    return protocol, source


def _state_protocol_sha(payload: dict[str, Any]) -> str | None:
    config = payload.get("config", {})
    if not isinstance(config, dict):
        return None
    return config.get("protocol_sha256") or config.get(
        "association_protocol_sha256"
    )


def _inspect_universal_upstreams(
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
        payload = _read_json(path)
        reduced = dict(specification)
        reduced.pop("expected_job_count", None)
        row = inspect_upstream_state(reduced, payload)
        expected_count = specification.get("expected_job_count")
        if row["complete"] and expected_count is not None:
            jobs = payload.get("jobs", {})
            if len(jobs) != int(expected_count):
                raise RuntimeError(
                    f"upstream {specification['state_id']} job count mismatch"
                )
            invalid = {
                key: value.get("status")
                for key, value in jobs.items()
                if not isinstance(value, dict)
                or value.get("status") not in {"complete", "already_complete"}
            }
            if invalid:
                raise RuntimeError(
                    f"upstream {specification['state_id']} jobs incomplete: {invalid}"
                )
        row.update(path=str(path), sha256=sha256_file(path))
        rows.append(row)
    return {
        "all_complete": all(row["complete"] for row in rows),
        "terminal_blocks": [row for row in rows if row["terminal_block"]],
        "states": rows,
    }


def _route_once(protocol: dict[str, Any]) -> dict[str, Any]:
    routing = protocol["routing"]
    universal_path = _repo_path(routing["universal_domain_state"])
    if not universal_path.is_file():
        return {"status": "waiting", "reason": "universal-domain-state-missing"}
    universal = _read_json(universal_path)
    if _state_protocol_sha(universal) != routing["universal_domain_protocol_sha256"]:
        raise RuntimeError("universal-domain state protocol hash mismatch")
    universal_status = str(universal.get("status", "missing_status"))
    if universal_status == routing["universal_pass_status"]:
        upstream = _inspect_universal_upstreams(protocol["universal_upstreams"])
        if upstream["terminal_blocks"]:
            return {
                "status": "blocked",
                "reason": "universal-upstream-terminal-block",
                "branch": "universal",
                "upstream": upstream,
            }
        if not upstream["all_complete"]:
            return {
                "status": "waiting",
                "reason": "universal-upstreams-incomplete",
                "branch": "universal",
                "upstream": upstream,
            }
        hierarchy_source = _read_json(
            _repo_path(protocol["source_protocols"]["hierarchical"]["path"])
        )
        formal_root = _repo_path(
            protocol["branches"]["universal"]["formal_campaign_root"]
        )
        missing_formal_artifacts = []
        for run_id in hierarchy_source["formal_run_ids"]:
            manifest_path = formal_root / run_id / "run_manifest.json"
            result_path = formal_root / run_id / "result.json"
            if not manifest_path.is_file() or not result_path.is_file():
                missing_formal_artifacts.extend(
                    str(path)
                    for path in (manifest_path, result_path)
                    if not path.is_file()
                )
                continue
            manifest = _read_json(manifest_path)
            result = _read_json(result_path)
            if result.get("protocol_fingerprint") != manifest.get(
                "protocol_fingerprint"
            ):
                raise RuntimeError(
                    f"universal formal result/manifest mismatch: {run_id}"
                )
        if missing_formal_artifacts:
            return {
                "status": "waiting",
                "reason": "universal-primary-formal-artifacts-incomplete",
                "branch": "universal",
                "missing_artifacts": missing_formal_artifacts,
                "upstream": upstream,
            }
        return {
            "status": "ready",
            "branch": "universal",
            "universal_domain_state_path": str(universal_path),
            "universal_domain_state_sha256": sha256_file(universal_path),
            "upstream": upstream,
        }
    if universal_status in set(routing["universal_failure_statuses"]):
        rerun_path = _repo_path(routing["fine_rerun_state"])
        if not rerun_path.is_file():
            return {
                "status": "waiting",
                "reason": "fine-rerun-state-missing",
                "branch": "finetuned",
            }
        rerun = _read_json(rerun_path)
        if _state_protocol_sha(rerun) != routing["fine_rerun_protocol_sha256"]:
            raise RuntimeError("fine-tuned rerun state protocol hash mismatch")
        rerun_status = str(rerun.get("status", "missing_status"))
        if rerun_status == "complete":
            if rerun.get("disposition") != routing["fine_rerun_complete_disposition"]:
                raise RuntimeError("fine-tuned rerun completed with another disposition")
            return {
                "status": "ready",
                "branch": "finetuned",
                "universal_domain_failure_status": universal_status,
                "universal_domain_state_path": str(universal_path),
                "universal_domain_state_sha256": sha256_file(universal_path),
                "fine_rerun_state_path": str(rerun_path),
                "fine_rerun_state_sha256": sha256_file(rerun_path),
            }
        if rerun_status.startswith(_TERMINAL_PREFIXES):
            return {
                "status": "blocked",
                "reason": "fine-rerun-terminal-block",
                "branch": "finetuned",
                "rerun_status": rerun_status,
                "rerun_path": str(rerun_path),
            }
        return {
            "status": "waiting",
            "reason": "fine-rerun-incomplete",
            "branch": "finetuned",
            "rerun_status": rerun_status,
            "rerun_path": str(rerun_path),
        }
    if universal_status.startswith("failed"):
        return {
            "status": "blocked",
            "reason": "universal-domain-runtime-failure",
            "universal_status": universal_status,
        }
    return {
        "status": "waiting",
        "reason": "universal-domain-decision-incomplete",
        "universal_status": universal_status,
    }


def _replace_branch_paths(
    hierarchical: dict[str, Any],
    association: dict[str, Any],
    *,
    branch: str,
    branch_config: dict[str, Any],
) -> None:
    formal_protocol = str(branch_config["formal_campaign_protocol"])
    formal_root = str(branch_config["formal_campaign_root"])
    size_protocol = str(branch_config["size_campaign_protocol"])
    velocity_protocol = str(branch_config["velocity_campaign_protocol"])
    fixed_protocol = str(branch_config["fixed_campaign_protocol"])
    hierarchical["protocol_id"] = f"llzto-hierarchical-transport-{branch}-v2"
    hierarchical["formal_campaign_protocol_path"] = formal_protocol
    hierarchical["formal_campaign_root"] = formal_root
    roles = hierarchical["sensitivity_roles"]
    velocity = roles["velocity_design"]
    velocity["reference_campaign_root"] = formal_root
    velocity["reference_protocol_path"] = formal_protocol
    velocity["supplemental_campaign_root"] = str(
        _read_json(_repo_path(velocity_protocol))["root_dir"]
    )
    velocity["supplemental_protocol_path"] = velocity_protocol
    roles["finite_size_campaign_root"] = str(
        _read_json(_repo_path(size_protocol))["root_dir"]
    )
    roles["finite_size_protocol_path"] = size_protocol
    roles["fixed_experimental_volume_campaign_root"] = str(
        _read_json(_repo_path(fixed_protocol))["root_dir"]
    )
    roles["fixed_experimental_volume_protocol_path"] = fixed_protocol

    association["protocol_id"] = (
        f"llzto-mechanism-transport-association-{branch}-v2"
    )
    formal = association["formal_campaign"]
    formal["protocol_path"] = formal_protocol
    formal["protocol_sha256"] = sha256_file(_repo_path(formal_protocol))
    formal["campaign_id"] = _read_json(_repo_path(formal_protocol))["campaign_id"]
    formal["campaign_root"] = formal_root
    association["mechanism_inputs"]["analysis_root"] = branch_config[
        "mechanism_root"
    ]


def derive_branch_analysis_protocols(
    supervisor_protocol_path: Path | str,
    branch: str,
) -> dict[str, dict[str, Any]]:
    """Derive all analysis protocols with unchanged statistics and thresholds."""
    protocol, source = validate_research_analysis_protocol(supervisor_protocol_path)
    if branch not in protocol["branches"]:
        raise ValueError(f"unknown research branch {branch!r}")
    branch_config = protocol["branches"][branch]
    for protocol_key, root_key in (
        ("formal_campaign_protocol", "formal_campaign_root"),
        ("ensemble_campaign_protocol", "ensemble_campaign_root"),
    ):
        campaign_path = _repo_path(branch_config[protocol_key])
        campaign_payload = _read_json(campaign_path)
        if _repo_path(campaign_payload["root_dir"]) != _repo_path(
            branch_config[root_key]
        ):
            raise RuntimeError(
                f"{branch} {protocol_key} root differs from branch declaration"
            )
    outputs = protocol["outputs"]
    output_root = _repo_path(outputs["root_template"].format(branch=branch))
    protocol_root = _repo_path(
        outputs["protocol_root_template"].format(branch=branch)
    )
    source_protocols = protocol["source_protocols"]
    hierarchical_source = _repo_path(source_protocols["hierarchical"]["path"])
    association_source = _repo_path(
        source_protocols["mechanism_association"]["path"]
    )
    hierarchical = copy.deepcopy(_read_json(hierarchical_source))
    association = copy.deepcopy(_read_json(association_source))
    _replace_branch_paths(
        hierarchical,
        association,
        branch=branch,
        branch_config=branch_config,
    )

    common_derivation = {
        "research_supervisor_protocol_path": str(source),
        "research_supervisor_protocol_sha256": sha256_file(source),
        "branch": branch,
        "model_branch_isolation": True,
        "statistics_and_acceptance_thresholds_unchanged": True,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    hierarchical["derivation"] = {
        **common_derivation,
        "source_path": str(hierarchical_source),
        "source_sha256": sha256_file(hierarchical_source),
    }
    hierarchical["derivation_fingerprint"] = fingerprint(hierarchical)
    hierarchical_path = protocol_root / "hierarchical-transport.json"
    _write_or_verify(
        hierarchical_path,
        hierarchical,
        label="branch hierarchical protocol",
        fingerprint_field="derivation_fingerprint",
    )

    association["derivation"] = {
        **common_derivation,
        "source_path": str(association_source),
        "source_sha256": sha256_file(association_source),
    }
    association["derivation_fingerprint"] = fingerprint(association)
    association_path = protocol_root / "mechanism-association.json"
    _write_or_verify(
        association_path,
        association,
        label="branch mechanism-association protocol",
        fingerprint_field="derivation_fingerprint",
    )

    ensemble_source = _repo_path(source_protocols["ensemble"]["path"])
    ensemble = copy.deepcopy(_read_json(ensemble_source))
    ensemble["protocol_id"] = f"llzto-ensemble-sensitivity-{branch}-v2"
    ensemble["reference"].update(
        campaign_root=branch_config["formal_campaign_root"],
        campaign_protocol_path=branch_config["formal_campaign_protocol"],
        campaign_protocol_sha256=sha256_file(
            _repo_path(branch_config["formal_campaign_protocol"])
        ),
    )
    ensemble["comparison"].update(
        campaign_root=branch_config["ensemble_campaign_root"],
        campaign_protocol_path=branch_config["ensemble_campaign_protocol"],
        campaign_protocol_sha256=sha256_file(
            _repo_path(branch_config["ensemble_campaign_protocol"])
        ),
    )
    ensemble["output_path"] = str(output_root / outputs["ensemble"])
    ensemble["derivation"] = {
        **common_derivation,
        "source_path": str(ensemble_source),
        "source_sha256": sha256_file(ensemble_source),
    }
    ensemble["derivation_fingerprint"] = fingerprint(ensemble)
    ensemble_path = protocol_root / "ensemble-sensitivity.json"
    _write_or_verify(
        ensemble_path,
        ensemble,
        label="branch ensemble protocol",
        fingerprint_field="derivation_fingerprint",
    )

    temperature_source = _repo_path(
        source_protocols["mechanism_temperature"]["path"]
    )
    temperature = copy.deepcopy(_read_json(temperature_source))
    temperature["protocol_id"] = (
        f"llzto-mechanism-temperature-robustness-{branch}-v2"
    )
    temperature["input"].update(
        primary_protocol_path=str(association_path),
        primary_protocol_sha256=sha256_file(association_path),
        primary_report_path=str(
            output_root / outputs["mechanism_association"]
        ),
    )
    temperature["output_path"] = str(
        output_root / outputs["mechanism_temperature"]
    )
    temperature["derivation"] = {
        **common_derivation,
        "source_path": str(temperature_source),
        "source_sha256": sha256_file(temperature_source),
    }
    temperature["derivation_fingerprint"] = fingerprint(temperature)
    temperature_path = protocol_root / "mechanism-temperature-robustness.json"
    _write_or_verify(
        temperature_path,
        temperature,
        label="branch mechanism-temperature protocol",
        fingerprint_field="derivation_fingerprint",
    )

    haven_source = _repo_path(source_protocols["haven"]["path"])
    haven = copy.deepcopy(_read_json(haven_source))
    haven["protocol_id"] = f"llzto-haven-convention-validation-{branch}-v2"
    haven["primary_hierarchical_input"].update(
        report_path=str(output_root / outputs["hierarchical"]),
        analysis_protocol_path=str(hierarchical_path),
        analysis_protocol_sha256=sha256_file(hierarchical_path),
    )
    haven["formal_campaign"].update(
        root=branch_config["formal_campaign_root"],
        protocol_path=branch_config["formal_campaign_protocol"],
        protocol_sha256=sha256_file(
            _repo_path(branch_config["formal_campaign_protocol"])
        ),
    )
    haven["output_path"] = str(output_root / outputs["haven"])
    haven["derivation"] = {
        **common_derivation,
        "source_path": str(haven_source),
        "source_sha256": sha256_file(haven_source),
    }
    haven["derivation_fingerprint"] = fingerprint(haven)
    haven_path = protocol_root / "haven-convention-validation.json"
    _write_or_verify(
        haven_path,
        haven,
        label="branch Haven protocol",
        fingerprint_field="derivation_fingerprint",
    )
    return {
        "hierarchical": {
            "path": str(hierarchical_path),
            "sha256": sha256_file(hierarchical_path),
        },
        "mechanism_association": {
            "path": str(association_path),
            "sha256": sha256_file(association_path),
        },
        "ensemble": {"path": str(ensemble_path), "sha256": sha256_file(ensemble_path)},
        "mechanism_temperature": {
            "path": str(temperature_path),
            "sha256": sha256_file(temperature_path),
        },
        "haven": {"path": str(haven_path), "sha256": sha256_file(haven_path)},
    }


def _report_record(
    path: Path,
    payload: dict[str, Any],
    *,
    complete: bool,
    scientific_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "complete" if complete else "incomplete",
        "path": str(path),
        "sha256": sha256_file(path),
        "complete": bool(complete),
        "report_kind": payload.get("report_kind"),
        "scientific_outcome": scientific_outcome or {},
    }


def _build_core_reports(
    protocol: dict[str, Any],
    branch: str,
    derived: dict[str, dict[str, Any]],
) -> dict[str, tuple[Path, dict[str, Any], bool, dict[str, Any]]]:
    branch_config = protocol["branches"][branch]
    outputs = protocol["outputs"]
    root = _repo_path(outputs["root_template"].format(branch=branch))
    formal_root = _repo_path(branch_config["formal_campaign_root"])
    hierarchical_protocol = Path(derived["hierarchical"]["path"])
    association_protocol = Path(derived["mechanism_association"]["path"])
    mechanism_root = _repo_path(branch_config["mechanism_root"])

    definitions: dict[
        str,
        tuple[
            Path,
            str | None,
            Callable[[], dict[str, Any]],
            Callable[[dict[str, Any]], bool],
            Callable[[dict[str, Any]], dict[str, Any]],
        ],
    ] = {
        "campaign_report": (
            root / outputs["campaign_report"],
            None,
            lambda: build_campaign_report(formal_root),
            lambda row: row.get("numerical_gate", {}).get(
                "all_energy_drift_checks_pass"
            )
            is True,
            lambda row: {
                "selected_timestep_fs": row.get("numerical_gate", {}).get(
                    "selected_timestep_fs"
                )
            },
        ),
        "hierarchical": (
            root / outputs["hierarchical"],
            "report_fingerprint",
            lambda: build_hierarchical_transport_report(
                formal_root, hierarchical_protocol
            ),
            lambda row: row.get("hierarchical_gate_pass") is True,
            lambda row: {
                "tracer_analysis_complete": row.get("estimators", {})
                .get("tracer", {})
                .get("analysis_gate_pass"),
                "collective_analysis_complete": row.get("estimators", {})
                .get("collective", {})
                .get("analysis_gate_pass"),
            },
        ),
        "nested_velocity": (
            root / outputs["nested_velocity"],
            "report_fingerprint",
            lambda: build_velocity_report(hierarchical_protocol),
            lambda row: row.get("result", {}).get("nested_velocity_gate_pass")
            is True,
            lambda row: {
                "occupancy_effect_support": {
                    name: value.get("occupancy_variance_boundary_test", {}).get(
                        "occupancy_variance_supported"
                    )
                    for name, value in row.get("result", {})
                    .get("estimators", {})
                    .items()
                }
            },
        ),
        "transport_sensitivity": (
            root / outputs["transport_sensitivity"],
            "report_fingerprint",
            lambda: build_sensitivity_report(hierarchical_protocol),
            _sensitivity_analysis_complete,
            lambda row: {
                "all_robustness_equivalence_supported": row.get(
                    "sensitivity_gate_pass"
                ),
                "finite_size_equivalence": row.get("finite_size", {}).get(
                    "finite_size_equivalence_gate_pass"
                ),
                "fixed_volume_robustness": row.get(
                    "fixed_experimental_volume", {}
                ).get("fixed_volume_robustness_gate_pass"),
                "npt_volume_robustness": row.get("npt_volume", {}).get(
                    "volume_robustness_gate_pass"
                ),
                "failed_equivalence_fails_completeness": False,
            },
        ),
        "mechanism_association": (
            root / outputs["mechanism_association"],
            "report_fingerprint",
            lambda: build_mechanism_transport_report(
                formal_root, mechanism_root, association_protocol
            ),
            lambda row: row.get("input_gate_pass") is True
            and row.get("analysis", {}).get("grid_gate_pass") is True
            and len(row.get("analysis_records", [])) == 25,
            lambda row: {
                "association_support_count": row.get("analysis", {}).get(
                    "association_support_count"
                ),
                "causal_claim_allowed": row.get("analysis", {}).get(
                    "causal_mechanism_claim_allowed"
                ),
                "null_association_fails_completeness": False,
            },
        ),
    }

    def run_one(
        name: str,
    ) -> tuple[str, Path, dict[str, Any], bool, dict[str, Any]]:
        path, fingerprint_field, builder, validator, outcome = definitions[name]
        payload = builder()
        payload = _write_or_verify(
            path,
            payload,
            label=name,
            fingerprint_field=fingerprint_field,
        )
        return name, path, payload, bool(validator(payload)), outcome(payload)

    completed: dict[str, tuple[Path, dict[str, Any], bool, dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(run_one, name): name for name in definitions}
        for future in as_completed(futures):
            name, path, payload, complete, outcome = future.result()
            completed[name] = (path, payload, complete, outcome)
    return completed


def _build_experiment(
    protocol: dict[str, Any],
    branch: str,
    hierarchical_path: Path,
) -> tuple[Path, dict[str, Any], bool, dict[str, Any]]:
    outputs = protocol["outputs"]
    root = _repo_path(outputs["root_template"].format(branch=branch))
    benchmark_path = _repo_path(
        protocol["source_protocols"]["experimental_benchmarks"]["path"]
    )
    hierarchical = _read_json(hierarchical_path)
    report = build_hierarchical_validation_report(
        hierarchical,
        load_benchmarks(benchmark_path),
        hierarchical_report_path=hierarchical_path,
        benchmark_path=benchmark_path,
    )
    destination = root / outputs["experimental_validation"]
    report = _write_or_verify(
        destination,
        report,
        label="experimental validation",
        fingerprint_field="report_fingerprint",
    )
    complete = bool(
        report.get("n_eligible_measurements") == 9
        and report.get("n_evaluated") == 9
        and report.get("n_blocked") == 0
    )
    outcome = {
        "compatible": sum(
            row.get("compatible_with_simulation_prediction") is True
            for row in report.get("comparisons", [])
        ),
        "incompatible": sum(
            row.get("compatible_with_simulation_prediction") is False
            for row in report.get("comparisons", [])
        ),
        "scientific_incompatibility_fails_completeness": False,
    }
    return destination, report, complete, outcome


def _build_extension_reports(
    protocol: dict[str, Any],
    branch: str,
    derived: dict[str, dict[str, Any]],
) -> dict[str, tuple[Path, dict[str, Any], bool, dict[str, Any]]]:
    outputs = protocol["outputs"]
    root = _repo_path(outputs["root_template"].format(branch=branch))
    definitions: dict[
        str,
        tuple[
            Path,
            str,
            Callable[[], dict[str, Any]],
            Callable[[dict[str, Any]], bool],
            Callable[[dict[str, Any]], dict[str, Any]],
        ],
    ] = {
        "ensemble": (
            root / outputs["ensemble"],
            "report_fingerprint",
            lambda: build_ensemble_sensitivity_report(derived["ensemble"]["path"]),
            lambda row: row.get("analysis_completeness_gate_pass") is True,
            lambda row: {
                "ensemble_robustness_supported": row.get(
                    "ensemble_robustness_gate_pass"
                ),
                "failed_equivalence_fails_completeness": row.get(
                    "failed_equivalence_fails_computational_completeness"
                ),
            },
        ),
        "mechanism_temperature": (
            root / outputs["mechanism_temperature"],
            "report_fingerprint",
            lambda: build_temperature_robustness_report(
                derived["mechanism_temperature"]["path"]
            ),
            lambda row: row.get("robustness_completeness_gate_pass") is True,
            lambda row: {
                "primary_support_count": row.get("analysis", {}).get(
                    "primary_v1_support_count"
                ),
                "retained_after_categorical_temperature_count": row.get(
                    "analysis", {}
                ).get("retained_association_count"),
                "null_or_downgraded_result_fails_completeness": False,
            },
        ),
        "haven": (
            root / outputs["haven"],
            "report_fingerprint",
            lambda: build_haven_validation_report(derived["haven"]["path"]),
            lambda row: row.get("analysis_completeness_gate_pass") is True,
            lambda row: {
                "experimental_haven_compatible": row.get(
                    "experimental_comparison", {}
                ).get("compatible_with_new_configuration_prediction"),
                "scientific_incompatibility_fails_completeness": row.get(
                    "scientific_incompatibility_fails_completeness"
                ),
            },
        ),
    }
    results: dict[str, tuple[Path, dict[str, Any], bool, dict[str, Any]]] = {}
    for name, (path, fingerprint_field, builder, validator, outcome) in definitions.items():
        payload = _write_or_verify(
            path,
            builder(),
            label=name,
            fingerprint_field=fingerprint_field,
        )
        results[name] = (path, payload, bool(validator(payload)), outcome(payload))
    return results


def _update(path: Path, state: dict[str, Any], status: str, **fields: Any) -> None:
    state["status"] = status
    state.update(fields)
    state["updated_unix_time"] = time.time()
    atomic_write_json(path, state)


def run_research_analysis_supervisor(
    protocol_path: Path | str,
    *,
    state_path: Path | str,
) -> dict[str, Any]:
    """Route one model branch, execute all analyses, and retain negative outcomes."""
    protocol, source = validate_research_analysis_protocol(protocol_path)
    poll_seconds = float(protocol["resources"]["poll_seconds"])
    if not 5 <= poll_seconds <= 60:
        raise ValueError("research analysis poll_seconds must be between 5 and 60")
    output = Path(state_path).resolve()
    locked_paths = [
        source,
        Path(__file__).resolve(),
        Path(__file__).with_name("ensemble_sensitivity.py").resolve(),
        Path(__file__).with_name("haven_validation.py").resolve(),
        Path(__file__).with_name("mechanism_temperature_robustness.py").resolve(),
        Path(__file__).with_name("mechanism_transport.py").resolve(),
        Path(__file__).with_name("report.py").resolve(),
        Path(__file__).with_name("transport_sensitivity.py").resolve(),
        Path(__file__).with_name("transport_statistics.py").resolve(),
        Path(__file__).with_name("validation.py").resolve(),
        Path(__file__).with_name("velocity_statistics.py").resolve(),
        *[
            _repo_path(record["path"])
            for record in protocol["source_protocols"].values()
        ],
        _repo_path(protocol["routing"]["universal_domain_protocol"]),
        _repo_path(protocol["routing"]["fine_tuning_protocol"]),
        _repo_path(protocol["routing"]["fine_rerun_protocol"]),
    ]
    locked_files = [
        {"path": str(path), "sha256": sha256_file(path)} for path in locked_paths
    ]

    def verify_locks() -> None:
        for row in locked_files:
            if sha256_file(row["path"]) != row["sha256"]:
                raise RuntimeError(f"research analysis locked file changed: {row['path']}")

    config = {
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "locked_files": locked_files,
    }
    state_fingerprint = fingerprint(config)
    if output.is_file():
        state = _read_json(output)
        if state.get("queue_fingerprint") != state_fingerprint:
            raise RuntimeError(f"research analysis configuration changed: {output}")
    else:
        state = {
            "schema_version": "1.0",
            "queue_fingerprint": state_fingerprint,
            "config": config,
            "created_unix_time": time.time(),
            "stages": {},
        }
        _update(output, state, "created")

    try:
        while True:
            verify_locks()
            routing = _route_once(protocol)
            if routing["status"] == "ready":
                branch = str(routing["branch"])
                state["routing"] = routing
                break
            if routing["status"] == "blocked":
                _update(
                    output,
                    state,
                    "blocked_upstream_evidence",
                    blocker=routing,
                    waiting=None,
                )
                return state
            _update(
                output,
                state,
                "waiting_for_model_branch_and_upstreams",
                waiting={"checked_unix_time": time.time(), **routing},
            )
            time.sleep(poll_seconds)

        derived = derive_branch_analysis_protocols(source, branch)
        state["stages"]["derived_protocols"] = {
            "status": "complete",
            "protocols": derived,
        }
        lock_path = _repo_path(protocol["resources"]["cpu_lock"])
        lock_handle = None
        while lock_handle is None:
            verify_locks()
            lock_handle = acquire_analysis_lock(lock_path)
            if lock_handle is None:
                _update(
                    output,
                    state,
                    "waiting_for_analysis_cpu_lock",
                    waiting={
                        "cpu_lock_path": str(lock_path),
                        "checked_unix_time": time.time(),
                    },
                )
                time.sleep(poll_seconds)
        try:
            _update(
                output,
                state,
                "running_complete_branch_analyses",
                active_branch=branch,
                waiting=None,
            )
            core = _build_core_reports(protocol, branch, derived)
            for name, (path, payload, complete, outcome) in core.items():
                state["stages"][name] = _report_record(
                    path,
                    payload,
                    complete=complete,
                    scientific_outcome=outcome,
                )
            incomplete = [name for name, value in core.items() if not value[2]]
            if incomplete:
                _update(
                    output,
                    state,
                    "blocked_incomplete_primary_analysis",
                    blockers=incomplete,
                    active_branch=branch,
                )
                return state

            hierarchical_path = core["hierarchical"][0]
            experiment = _build_experiment(
                protocol, branch, hierarchical_path
            )
            state["stages"]["experimental_validation"] = _report_record(
                experiment[0],
                experiment[1],
                complete=experiment[2],
                scientific_outcome=experiment[3],
            )
            if not experiment[2]:
                _update(
                    output,
                    state,
                    "blocked_incomplete_experimental_analysis",
                    blockers=["experimental_validation"],
                    active_branch=branch,
                )
                return state

            extensions = _build_extension_reports(protocol, branch, derived)
            for name, (path, payload, complete, outcome) in extensions.items():
                state["stages"][name] = _report_record(
                    path,
                    payload,
                    complete=complete,
                    scientific_outcome=outcome,
                )
            incomplete_extensions = [
                name for name, value in extensions.items() if not value[2]
            ]
            if incomplete_extensions:
                _update(
                    output,
                    state,
                    "blocked_incomplete_extended_analysis",
                    blockers=incomplete_extensions,
                    active_branch=branch,
                )
                return state
        finally:
            release_analysis_lock(lock_handle)

        outputs = protocol["outputs"]
        root = _repo_path(outputs["root_template"].format(branch=branch))
        reports = {
            name: {
                "path": row["path"],
                "sha256": row["sha256"],
                "complete": row["complete"],
                "scientific_outcome": row["scientific_outcome"],
            }
            for name, row in state["stages"].items()
            if isinstance(row, dict) and "path" in row and "complete" in row
        }
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "manifest_kind": "llzto-complete-research-analysis-v2",
            "branch": branch,
            "model_branch_isolation": True,
            "supervisor_protocol_path": str(source),
            "supervisor_protocol_sha256": sha256_file(source),
            "routing": state["routing"],
            "derived_protocols": derived,
            "reports": reports,
            "analysis_completeness_gate_pass": bool(
                reports and all(row["complete"] for row in reports.values())
            ),
            "negative_scientific_outcomes_retained": True,
            "claim_narrowing_flags": {
                "size_or_volume_non_equivalence": not bool(
                    reports["transport_sensitivity"]["scientific_outcome"].get(
                        "all_robustness_equivalence_supported"
                    )
                ),
                "production_ensemble_non_equivalence": not bool(
                    reports["ensemble"]["scientific_outcome"].get(
                        "ensemble_robustness_supported"
                    )
                ),
                "experimental_haven_incompatibility": not bool(
                    reports["haven"]["scientific_outcome"].get(
                        "experimental_haven_compatible"
                    )
                ),
            },
            "implementation_path": str(Path(__file__).resolve()),
            "implementation_sha256": sha256_file(__file__),
        }
        manifest["manifest_fingerprint"] = fingerprint(manifest)
        manifest_path = root / outputs["analysis_manifest"]
        manifest = _write_or_verify(
            manifest_path,
            manifest,
            label="research analysis manifest",
            fingerprint_field="manifest_fingerprint",
        )
        state["stages"]["analysis_manifest"] = {
            "status": "complete",
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "branch": branch,
            "claim_narrowing_flags": manifest["claim_narrowing_flags"],
        }
        _update(
            output,
            state,
            "complete",
            active_branch=branch,
            disposition="complete_analysis_ready_for_publication_v2",
            analysis_manifest_path=str(manifest_path),
            analysis_manifest_sha256=sha256_file(manifest_path),
            claim_narrowing_flags=manifest["claim_narrowing_flags"],
            waiting=None,
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
    args = parser.parse_args()
    result = run_research_analysis_supervisor(
        args.protocol,
        state_path=args.state,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
