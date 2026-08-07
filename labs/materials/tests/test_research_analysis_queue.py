from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.provenance import fingerprint, sha256_file  # noqa: E402
from matfactory.research_analysis_queue import (  # noqa: E402
    _route_once,
    _sensitivity_analysis_complete,
    derive_branch_analysis_protocols,
    run_research_analysis_supervisor,
    validate_research_analysis_protocol,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fingerprinted(payload: dict, field: str = "report_fingerprint") -> dict:
    payload[field] = fingerprint(payload)
    return payload


def _complete_sensitivity_comparison(*, equivalent: bool = False) -> dict:
    return {
        "comparison_gate_pass": True,
        "estimators": {
            name: {
                "analysis_gate_pass": True,
                "equivalence_supported": equivalent,
            }
            for name in (
                "tracer",
                "collective",
                "collective_to_tracer_ratio",
            )
        },
    }


def test_sensitivity_completeness_separates_estimability_from_equivalence():
    negative_but_complete = {
        "finite_size": _complete_sensitivity_comparison(),
        "fixed_experimental_volume": _complete_sensitivity_comparison(),
        "npt_volume": {
            "by_temperature": [
                _complete_sensitivity_comparison() for _ in range(5)
            ],
            "activation_energy_difference": {
                "tracer": {"analysis_gate_pass": True, "within_margin": False},
                "collective": {
                    "analysis_gate_pass": True,
                    "within_margin": False,
                },
            },
        },
        "sensitivity_gate_pass": False,
    }
    assert _sensitivity_analysis_complete(negative_but_complete) is True

    unresolved = json.loads(json.dumps(negative_but_complete))
    unresolved["finite_size"]["comparison_gate_pass"] = False
    unresolved["finite_size"]["estimators"]["tracer"][
        "analysis_gate_pass"
    ] = False
    assert _sensitivity_analysis_complete(unresolved) is False

    missing_temperature = json.loads(json.dumps(negative_but_complete))
    missing_temperature["npt_volume"]["by_temperature"].pop()
    assert _sensitivity_analysis_complete(missing_temperature) is False


def _universal_ready_protocol(tmp_path: Path) -> tuple[Path, dict]:
    source = ROOT / "analysis/protocols/llzto_research_analysis_supervisor_v2.json"
    protocol = json.loads(source.read_text())
    universal_state = tmp_path / "universal-domain.json"
    _write_json(
        universal_state,
        {
            "status": "complete",
            "config": {
                "protocol_sha256": protocol["routing"][
                    "universal_domain_protocol_sha256"
                ]
            },
        },
    )
    protocol["routing"]["universal_domain_state"] = str(universal_state)
    for index, specification in enumerate(protocol["universal_upstreams"]):
        state_path = tmp_path / f"upstream-{index}.json"
        run_ids = specification.get("expected_run_ids")
        expected_count = specification.get("expected_job_count")
        if run_ids is not None:
            job_ids = run_ids
        else:
            job_ids = [f"job-{ordinal}" for ordinal in range(expected_count)]
        _write_json(
            state_path,
            {
                "status": "complete",
                "config": {
                    "protocol_sha256": specification[
                        "expected_protocol_sha256"
                    ],
                    "run_ids": run_ids or [],
                },
                "jobs": {
                    job_id: {"status": "complete"} for job_id in job_ids
                },
            },
        )
        specification["path"] = str(state_path)
    protocol["outputs"]["root_template"] = str(
        tmp_path / "analysis/{branch}"
    )
    protocol["outputs"]["protocol_root_template"] = str(
        tmp_path / "protocols/{branch}"
    )
    protocol["resources"]["cpu_lock"] = str(tmp_path / "analysis.lock")
    protocol_path = tmp_path / "research-analysis-protocol.json"
    _write_json(protocol_path, protocol)
    return protocol_path, protocol


def test_repository_research_protocol_locks_outcome_aware_branching():
    protocol, source = validate_research_analysis_protocol(
        ROOT / "analysis/protocols/llzto_research_analysis_supervisor_v2.json"
    )

    assert source.is_file()
    assert set(protocol["branches"]) == {"universal", "finetuned"}
    assert len(protocol["universal_upstreams"]) == 6
    assert "physical non-equivalence" in protocol["claim_boundary"]
    assert protocol["outputs"]["ensemble"] == "ensemble-sensitivity.json"
    assert protocol["outputs"]["haven"] == "haven-convention-validation.json"
    watchdog = json.loads(
        (
            ROOT
            / "analysis/protocols/llzto_research_analysis_watchdog_v2.json"
        ).read_text()
    )
    assert watchdog["managed"][0]["expected_protocol_sha256"] == sha256_file(
        source
    )


def test_router_selects_exactly_one_ready_branch(tmp_path):
    protocol_path, protocol = _universal_ready_protocol(tmp_path)
    loaded, _ = validate_research_analysis_protocol(protocol_path)
    synthetic_hierarchy = tmp_path / "routing-hierarchy.json"
    _write_json(synthetic_hierarchy, {"formal_run_ids": []})
    loaded["source_protocols"]["hierarchical"]["path"] = str(
        synthetic_hierarchy
    )
    universal = _route_once(loaded)

    assert universal["status"] == "ready"
    assert universal["branch"] == "universal"
    assert universal["upstream"]["all_complete"] is True

    universal_state = Path(loaded["routing"]["universal_domain_state"])
    _write_json(
        universal_state,
        {
            "status": "blocked_heldout_domain_failure",
            "config": {
                "protocol_sha256": loaded["routing"][
                    "universal_domain_protocol_sha256"
                ]
            },
        },
    )
    rerun_state = tmp_path / "fine-rerun.json"
    _write_json(
        rerun_state,
        {
            "status": "complete",
            "disposition": loaded["routing"][
                "fine_rerun_complete_disposition"
            ],
            "config": {
                "protocol_sha256": loaded["routing"][
                    "fine_rerun_protocol_sha256"
                ]
            },
        },
    )
    loaded["routing"]["fine_rerun_state"] = str(rerun_state)
    finetuned = _route_once(loaded)

    assert finetuned["status"] == "ready"
    assert finetuned["branch"] == "finetuned"
    assert finetuned["universal_domain_failure_status"] == (
        "blocked_heldout_domain_failure"
    )


def test_universal_protocol_derivation_rebinds_extension_outputs(tmp_path):
    protocol_path, _ = _universal_ready_protocol(tmp_path)
    derived = derive_branch_analysis_protocols(protocol_path, "universal")

    hierarchy = json.loads(Path(derived["hierarchical"]["path"]).read_text())
    association = json.loads(
        Path(derived["mechanism_association"]["path"]).read_text()
    )
    ensemble = json.loads(Path(derived["ensemble"]["path"]).read_text())
    temperature = json.loads(
        Path(derived["mechanism_temperature"]["path"]).read_text()
    )
    haven = json.loads(Path(derived["haven"]["path"]).read_text())

    assert hierarchy["formal_campaign_root"] == "runs/campaigns/llzto_q1_v1"
    assert association["formal_campaign"]["protocol_sha256"] == sha256_file(
        ROOT / "protocols/llzto_q1_v1.json"
    )
    assert ensemble["output_path"].endswith(
        "/analysis/universal/ensemble-sensitivity.json"
    )
    assert temperature["input"]["primary_report_path"].endswith(
        "/analysis/universal/mechanism-transport-association.json"
    )
    assert haven["primary_hierarchical_input"]["report_path"].endswith(
        "/analysis/universal/hierarchical-transport.json"
    )
    assert all(Path(row["path"]).is_file() for row in derived.values())


def test_complete_negative_robustness_is_retained_not_misreported_as_missing(
    tmp_path, monkeypatch
):
    protocol_path, protocol = _universal_ready_protocol(tmp_path)
    monkeypatch.setattr(
        "matfactory.research_analysis_queue._route_once",
        lambda _protocol: {
            "status": "ready",
            "branch": "universal",
            "synthetic_test_route": True,
        },
    )

    campaign_report = {
        "schema_version": "1.0",
        "numerical_gate": {
            "all_energy_drift_checks_pass": True,
            "selected_timestep_fs": 2.0,
        },
    }
    hierarchical = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "hierarchical-transport",
            "hierarchical_gate_pass": True,
            "estimators": {
                "tracer": {"analysis_gate_pass": True},
                "collective": {"analysis_gate_pass": True},
            },
        }
    )
    velocity = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "nested-velocity",
            "result": {
                "nested_velocity_gate_pass": True,
                "estimators": {},
            },
        }
    )
    sensitivity = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "transport-sensitivity",
            "finite_size": {
                **_complete_sensitivity_comparison(),
                "finite_size_equivalence_gate_pass": False,
            },
            "fixed_experimental_volume": {
                **_complete_sensitivity_comparison(),
                "fixed_volume_robustness_gate_pass": True
            },
            "npt_volume": {
                "by_temperature": [
                    _complete_sensitivity_comparison() for _ in range(5)
                ],
                "activation_energy_difference": {
                    "tracer": {"analysis_gate_pass": True},
                    "collective": {"analysis_gate_pass": True},
                },
                "volume_robustness_gate_pass": True,
            },
            "sensitivity_gate_pass": False,
        }
    )
    association = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "mechanism-transport-association",
            "input_gate_pass": True,
            "analysis_records": [{}] * 25,
            "analysis": {
                "grid_gate_pass": True,
                "association_support_count": 0,
                "causal_mechanism_claim_allowed": False,
            },
        }
    )
    experiment = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "hierarchical-experimental-validation",
            "n_eligible_measurements": 9,
            "n_evaluated": 9,
            "n_blocked": 0,
            "comparisons": [
                {"compatible_with_simulation_prediction": index < 4}
                for index in range(9)
            ],
        }
    )
    ensemble = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "production-ensemble-sensitivity",
            "analysis_completeness_gate_pass": True,
            "ensemble_robustness_gate_pass": False,
            "failed_equivalence_fails_computational_completeness": False,
        }
    )
    temperature = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "mechanism-categorical-temperature-robustness",
            "robustness_completeness_gate_pass": True,
            "analysis": {
                "primary_v1_support_count": 2,
                "retained_association_count": 1,
            },
        }
    )
    haven = _fingerprinted(
        {
            "schema_version": "1.0",
            "report_kind": "haven-convention-validation",
            "analysis_completeness_gate_pass": True,
            "scientific_incompatibility_fails_completeness": False,
            "experimental_comparison": {
                "compatible_with_new_configuration_prediction": False
            },
        }
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_campaign_report",
        lambda *_: campaign_report,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_hierarchical_transport_report",
        lambda *_: hierarchical,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_velocity_report",
        lambda *_: velocity,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_sensitivity_report",
        lambda *_: sensitivity,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_mechanism_transport_report",
        lambda *_: association,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_hierarchical_validation_report",
        lambda *_args, **_kwargs: experiment,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_ensemble_sensitivity_report",
        lambda *_: ensemble,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_temperature_robustness_report",
        lambda *_: temperature,
    )
    monkeypatch.setattr(
        "matfactory.research_analysis_queue.build_haven_validation_report",
        lambda *_: haven,
    )

    result = run_research_analysis_supervisor(
        protocol_path,
        state_path=tmp_path / "analysis-state.json",
    )
    manifest = json.loads(Path(result["analysis_manifest_path"]).read_text())

    assert result["status"] == "complete"
    assert result["active_branch"] == "universal"
    assert manifest["analysis_completeness_gate_pass"] is True
    assert manifest["claim_narrowing_flags"] == {
        "size_or_volume_non_equivalence": True,
        "production_ensemble_non_equivalence": True,
        "experimental_haven_incompatibility": True,
    }
    assert manifest["reports"]["transport_sensitivity"]["complete"] is True
    assert manifest["reports"]["ensemble"]["complete"] is True
    assert manifest["reports"]["mechanism_temperature"][
        "scientific_outcome"
    ]["primary_support_count"] == 2
    assert manifest["reports"]["mechanism_temperature"][
        "scientific_outcome"
    ]["retained_after_categorical_temperature_count"] == 1
