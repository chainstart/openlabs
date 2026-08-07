"""Audit structures and budget a hidden-order/soft-mode discovery study.

This first implementation is deliberately CPU-only.  It validates immutable
inputs, diagnoses occupational disorder, routes candidates to later stages,
and refuses to imply that disabled GPU or DFT stages have been executed.
"""

from __future__ import annotations

import json
import math
import re
import time
import warnings
from dataclasses import dataclass
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .provenance import (
    atomic_write_json,
    atomic_write_text,
    fingerprint,
    git_state,
    sha256_file,
)

_ROOT = Path(__file__).resolve().parents[2]
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EXECUTABLE_STAGES = {"structure_audit"}


@dataclass(frozen=True)
class DiscoveryCandidate:
    """One immutable structure input and its scientific role."""

    candidate_id: str
    path: Path
    source_url: str | None
    source_license: str | None
    role: str
    eligible_for_novelty: bool
    expected_composition_per_cell: dict[str, float]
    notes: str


@dataclass(frozen=True)
class DiscoveryProtocol:
    """Validated, materialized discovery protocol."""

    study_id: str
    title: str
    hypothesis: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    budget: dict[str, Any]
    screening: dict[str, Any]
    models: tuple[dict[str, str], ...]
    stages: dict[str, dict[str, Any]]
    gates: tuple[dict[str, Any], ...]
    candidates: tuple[DiscoveryCandidate, ...]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _require_positive_number(
    mapping: dict[str, Any], field: str, *, allow_zero: bool = False
) -> float:
    value = mapping.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{field} must be numeric")
    number = float(value)
    if (allow_zero and number < 0) or (not allow_zero and number <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field} must be {qualifier}")
    return number


def load_discovery_protocol(path: Path | str) -> DiscoveryProtocol:
    """Validate a one-day discovery protocol without loading atomistic models."""
    protocol_path = Path(path).resolve()
    payload = _read_json(protocol_path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("discovery schema_version must be '1.0'")

    study_id = payload.get("study_id")
    if not isinstance(study_id, str) or not _SAFE_ID.fullmatch(study_id):
        raise ValueError("study_id must be a safe lowercase identifier")
    title = payload.get("title")
    hypothesis = payload.get("hypothesis")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("hypothesis must be a non-empty string")

    root_dir = _repo_path(str(payload.get("root_dir", f"runs/discovery/{study_id}")))

    budget = payload.get("budget")
    if not isinstance(budget, dict):
        raise TypeError("budget must be an object")
    wall_hours = _require_positive_number(budget, "wall_time_hours")
    gpu_hours = _require_positive_number(budget, "gpu_hours", allow_zero=True)
    if wall_hours > 24:
        raise ValueError("one-day discovery wall_time_hours cannot exceed 24")
    if gpu_hours > wall_hours:
        raise ValueError("single-GPU gpu_hours cannot exceed wall_time_hours")
    max_candidates = budget.get("max_candidates")
    max_orderings = budget.get("max_orderings_per_candidate")
    max_soft_modes = budget.get("max_soft_modes")
    if not isinstance(max_candidates, int) or not 1 <= max_candidates <= 100:
        raise ValueError("max_candidates must be an integer from 1 to 100")
    if not isinstance(max_orderings, int) or not 1 <= max_orderings <= 128:
        raise ValueError("max_orderings_per_candidate must be an integer from 1 to 128")
    if not isinstance(max_soft_modes, int) or not 1 <= max_soft_modes <= 24:
        raise ValueError("max_soft_modes must be an integer from 1 to 24")
    _require_positive_number(budget, "estimated_relax_minutes_per_model")
    amplitudes = budget.get("mode_amplitudes")
    if (
        not isinstance(amplitudes, list)
        or not amplitudes
        or any(
            not isinstance(item, (int, float)) or isinstance(item, bool)
            for item in amplitudes
        )
    ):
        raise ValueError("mode_amplitudes must be a non-empty numeric list")

    screening = payload.get("screening")
    if not isinstance(screening, dict):
        raise TypeError("screening must be an object")
    for field in (
        "cif_occupancy_tolerance",
        "rationalization_absolute_tolerance",
        "composition_warning_absolute_atoms",
        "composition_block_absolute_atoms",
        "max_atoms_per_relaxation",
        "soft_mode_max_atoms",
    ):
        _require_positive_number(screening, field)
    max_denominator = screening.get("rationalization_max_denominator")
    if not isinstance(max_denominator, int) or not 2 <= max_denominator <= 128:
        raise ValueError(
            "rationalization_max_denominator must be an integer from 2 to 128"
        )
    if float(screening["composition_warning_absolute_atoms"]) >= float(
        screening["composition_block_absolute_atoms"]
    ):
        raise ValueError("composition warning threshold must be below block threshold")

    models = payload.get("models")
    if not isinstance(models, list) or len(models) < 2:
        raise ValueError("at least two independent model families are required")
    normalized_models: list[dict[str, str]] = []
    model_ids: set[str] = set()
    families: set[str] = set()
    for model in models:
        if not isinstance(model, dict):
            raise TypeError("each model must be an object")
        required = ("model_id", "family", "package")
        if any(
            not isinstance(model.get(field), str) or not model[field]
            for field in required
        ):
            raise ValueError("each model needs model_id, family, and package strings")
        model_id = str(model["model_id"])
        if not _SAFE_ID.fullmatch(model_id) or model_id in model_ids:
            raise ValueError(f"unsafe or duplicate model_id {model_id!r}")
        model_ids.add(model_id)
        families.add(str(model["family"]))
        normalized_models.append(
            {
                "model_id": model_id,
                "family": str(model["family"]),
                "package": str(model["package"]),
                "artifact": str(model.get("artifact", "unfrozen")),
            }
        )
    if len(families) < 2:
        raise ValueError("models must represent at least two independent families")

    stages = payload.get("stages")
    if not isinstance(stages, dict) or not stages:
        raise ValueError("stages must be a non-empty object")
    for name, spec in stages.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            raise TypeError("each stage must be a named object")
        if bool(spec.get("enabled")) and name not in _EXECUTABLE_STAGES:
            raise ValueError(
                f"stage {name!r} is enabled but this implementation only executes "
                "structure_audit"
            )
    if not bool(stages.get("structure_audit", {}).get("enabled")):
        raise ValueError("structure_audit must be enabled")

    gates = payload.get("gates", [])
    if not isinstance(gates, list) or any(not isinstance(item, dict) for item in gates):
        raise ValueError("gates must be a list of objects")

    candidate_specs = payload.get("candidates")
    if not isinstance(candidate_specs, list) or not candidate_specs:
        raise ValueError("candidates must be a non-empty list")
    if len(candidate_specs) > max_candidates:
        raise ValueError("candidate count exceeds budget.max_candidates")
    seen: set[str] = set()
    candidates: list[DiscoveryCandidate] = []
    for spec in candidate_specs:
        if not isinstance(spec, dict):
            raise TypeError("each candidate must be an object")
        candidate_id = spec.get("candidate_id")
        if (
            not isinstance(candidate_id, str)
            or not _SAFE_ID.fullmatch(candidate_id)
            or candidate_id in seen
        ):
            raise ValueError(f"unsafe or duplicate candidate_id {candidate_id!r}")
        seen.add(candidate_id)
        structure_path = spec.get("path")
        if not isinstance(structure_path, str) or not structure_path:
            raise ValueError(f"candidate {candidate_id} needs a structure path")
        expected = spec.get("expected_composition_per_cell", {})
        if not isinstance(expected, dict) or any(
            not isinstance(element, str)
            or not element
            or not isinstance(amount, (int, float))
            or isinstance(amount, bool)
            or float(amount) < 0
            for element, amount in expected.items()
        ):
            raise ValueError(
                f"candidate {candidate_id} has invalid expected composition"
            )
        candidates.append(
            DiscoveryCandidate(
                candidate_id=candidate_id,
                path=_repo_path(structure_path),
                source_url=(
                    str(spec["source_url"]) if spec.get("source_url") else None
                ),
                source_license=(
                    str(spec["source_license"]) if spec.get("source_license") else None
                ),
                role=str(spec.get("role", "screening-candidate")),
                eligible_for_novelty=bool(spec.get("eligible_for_novelty", True)),
                expected_composition_per_cell={
                    str(element): float(amount) for element, amount in expected.items()
                },
                notes=str(spec.get("notes", "")),
            )
        )

    return DiscoveryProtocol(
        study_id=study_id,
        title=title.strip(),
        hypothesis=hypothesis.strip(),
        protocol_path=protocol_path,
        protocol_sha256=sha256_file(protocol_path),
        root_dir=root_dir,
        budget=dict(budget),
        screening=dict(screening),
        models=tuple(normalized_models),
        stages={str(name): dict(spec) for name, spec in stages.items()},
        gates=tuple(dict(item) for item in gates),
        candidates=tuple(candidates),
    )


def _rationalize(
    value: float, max_denominator: int, tolerance: float
) -> dict[str, Any]:
    fraction: Fraction | None = None
    for denominator in range(1, max_denominator + 1):
        numerator = round(float(value) * denominator)
        candidate = Fraction(numerator, denominator)
        if abs(float(value) - float(candidate)) <= tolerance + 1e-12:
            fraction = candidate
            break
    if fraction is None:
        fraction = Fraction(float(value)).limit_denominator(max_denominator)
    approximated = fraction.numerator / fraction.denominator
    error = abs(float(value) - approximated)
    return {
        "fraction": f"{fraction.numerator}/{fraction.denominator}",
        "numerator": fraction.numerator,
        "denominator": fraction.denominator,
        "approximated": approximated,
        "absolute_error": error,
        "within_tolerance": error <= tolerance,
    }


def _model_environment(models: tuple[dict[str, str], ...]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for model in models:
        package = model["package"]
        try:
            installed = version(package)
        except PackageNotFoundError:
            installed = None
        output.append(
            {
                **model,
                "installed_version": installed,
                "available": installed is not None,
                "artifact_frozen": model["artifact"] != "unfrozen",
            }
        )
    return output


def _load_structure(path: Path, occupancy_tolerance: float) -> tuple[Any, list[str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if path.suffix.lower() == ".cif":
            from pymatgen.io.cif import CifParser

            parser = CifParser(str(path), occupancy_tolerance=occupancy_tolerance)
            structures = parser.parse_structures(primitive=False)
            if len(structures) != 1:
                raise ValueError(
                    f"expected one structure in {path}, found {len(structures)}"
                )
            structure = structures[0]
        else:
            from pymatgen.core import Structure

            structure = Structure.from_file(path, primitive=False)
    messages = list(dict.fromkeys(str(item.message) for item in caught))
    return structure, messages


def _species_symbol(species: Any) -> str:
    element = getattr(species, "element", None)
    if element is not None:
        return str(element.symbol)
    symbol = getattr(species, "symbol", None)
    return str(symbol if symbol is not None else species)


def _disorder_groups(
    structure: Any, *, max_denominator: int, tolerance: float
) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[str, dict[str, Any]] = {}
    denominators: list[int] = []
    for site in structure:
        if site.is_ordered:
            continue
        species = {
            _species_symbol(item): float(amount)
            for item, amount in site.species.items()
        }
        occupancy = sum(species.values())
        vacancy = max(0.0, 1.0 - occupancy)
        signature_payload = {
            "species": {
                key: round(value, 12) for key, value in sorted(species.items())
            },
            "vacancy_fraction": round(vacancy, 12),
        }
        signature = json.dumps(signature_payload, sort_keys=True, separators=(",", ":"))
        if signature not in grouped:
            rationalized = {
                key: _rationalize(value, max_denominator, tolerance)
                for key, value in sorted(species.items())
            }
            vacancy_rationalized = (
                _rationalize(vacancy, max_denominator, tolerance)
                if vacancy > 1e-12
                else None
            )
            for item in rationalized.values():
                if item["within_tolerance"]:
                    denominators.append(int(item["denominator"]))
            if vacancy_rationalized and vacancy_rationalized["within_tolerance"]:
                denominators.append(int(vacancy_rationalized["denominator"]))
            grouped[signature] = {
                "site_count": 0,
                "species": dict(sorted(species.items())),
                "occupancy_sum": occupancy,
                "vacancy_fraction": vacancy,
                "mixed_species": len(species) > 1,
                "rationalized_species": rationalized,
                "rationalized_vacancy": vacancy_rationalized,
            }
        grouped[signature]["site_count"] += 1

    groups = sorted(
        grouped.values(),
        key=lambda item: (
            tuple(item["species"]),
            tuple(item["species"].values()),
            item["vacancy_fraction"],
        ),
    )
    for group in groups:
        estimates: dict[str, float] = {}
        for element, row in group["rationalized_species"].items():
            estimates[element] = group["site_count"] * float(row["approximated"])
        if group["rationalized_vacancy"] is not None:
            estimates["Vacancy"] = group["site_count"] * float(
                group["rationalized_vacancy"]["approximated"]
            )
        group["rationalized_counts_in_expanded_cell"] = estimates

    minimum_multiplier = 1
    for denominator in denominators:
        minimum_multiplier = math.lcm(minimum_multiplier, denominator)
    return groups, minimum_multiplier


def _composition_check(
    observed: dict[str, float], expected: dict[str, float]
) -> dict[str, Any]:
    if not expected:
        return {
            "expected": {},
            "observed": observed,
            "delta_observed_minus_expected": {},
            "maximum_absolute_error_atoms": None,
        }
    elements = sorted(set(observed) | set(expected))
    delta = {
        element: float(observed.get(element, 0.0) - expected.get(element, 0.0))
        for element in elements
    }
    return {
        "expected": dict(sorted(expected.items())),
        "observed": dict(sorted(observed.items())),
        "delta_observed_minus_expected": delta,
        "maximum_absolute_error_atoms": max(abs(value) for value in delta.values()),
    }


def _stage_plan(
    route: str,
    protocol: DiscoveryProtocol,
    *,
    blocked: bool,
) -> dict[str, Any]:
    model_count = len(protocol.models)
    minutes = float(protocol.budget["estimated_relax_minutes_per_model"])
    if blocked or route == "ordered-reference-only":
        units = 0
        stage = None
    elif route == "constrained-hidden-order":
        units = int(protocol.budget["max_orderings_per_candidate"])
        stage = "ordering_enumeration"
    else:
        units = int(protocol.budget["max_soft_modes"]) * len(
            protocol.budget["mode_amplitudes"]
        )
        stage = "soft_mode_followup"
    relaxations = units * model_count
    return {
        "next_stage": stage,
        "candidate_realizations_or_distortions": units,
        "model_evaluations": relaxations,
        "estimated_gpu_hours": relaxations * minutes / 60.0,
        "authorized_now": bool(
            stage is not None and protocol.stages.get(stage, {}).get("enabled", False)
        ),
    }


def _audit_candidate(
    candidate: DiscoveryCandidate, protocol: DiscoveryProtocol
) -> dict[str, Any]:
    screening = protocol.screening
    structure, parser_warnings = _load_structure(
        candidate.path, float(screening["cif_occupancy_tolerance"])
    )
    composition = {
        str(element): float(amount)
        for element, amount in structure.composition.get_el_amt_dict().items()
    }
    disorder, minimum_multiplier = _disorder_groups(
        structure,
        max_denominator=int(screening["rationalization_max_denominator"]),
        tolerance=float(screening["rationalization_absolute_tolerance"]),
    )
    composition_check = _composition_check(
        composition, candidate.expected_composition_per_cell
    )
    expected_atoms = (
        sum(candidate.expected_composition_per_cell.values())
        if candidate.expected_composition_per_cell
        else sum(composition.values())
    )
    n_disordered = sum(int(group["site_count"]) for group in disorder)
    n_mixed = sum(
        int(group["site_count"]) for group in disorder if group["mixed_species"]
    )
    n_vacancy = sum(
        int(group["site_count"])
        for group in disorder
        if float(group["vacancy_fraction"]) > 1e-12
    )

    scientific_warnings: list[str] = []
    blockers: list[str] = []
    maximum_error = composition_check["maximum_absolute_error_atoms"]
    if maximum_error is not None:
        if maximum_error > float(screening["composition_block_absolute_atoms"]):
            blockers.append(
                "parsed occupancy composition differs from the declared exact cell "
                "composition beyond the frozen block threshold"
            )
        elif maximum_error > float(screening["composition_warning_absolute_atoms"]):
            scientific_warnings.append(
                "rounded average occupancies do not reproduce the declared exact "
                "cell composition; downstream enumeration must impose exact counts"
            )
    rationalization_failures = [
        row
        for group in disorder
        for row in [
            *group["rationalized_species"].values(),
            *(
                [group["rationalized_vacancy"]]
                if group["rationalized_vacancy"] is not None
                else []
            ),
        ]
        if not row["within_tolerance"]
    ]
    if rationalization_failures:
        scientific_warnings.append(
            "at least one occupancy cannot be rationalized within the frozen "
            "denominator and error limits"
        )
    if expected_atoms > float(screening["max_atoms_per_relaxation"]):
        blockers.append("expected ordered cell exceeds max_atoms_per_relaxation")

    if n_disordered:
        route = "constrained-hidden-order"
    elif expected_atoms <= float(screening["soft_mode_max_atoms"]):
        route = "soft-mode-precheck"
    else:
        route = "ordered-reference-only"

    symmetry: dict[str, Any] | None = None
    if not n_disordered:
        try:
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

            analyzer = SpacegroupAnalyzer(structure, symprec=0.1)
            symmetry = {
                "symbol": analyzer.get_space_group_symbol(),
                "number": analyzer.get_space_group_number(),
                "symprec_angstrom": 0.1,
            }
        except (TypeError, ValueError) as exc:
            scientific_warnings.append(
                f"ordered-structure symmetry analysis failed: {type(exc).__name__}: {exc}"
            )

    plan = _stage_plan(route, protocol, blocked=bool(blockers))
    return {
        "candidate_id": candidate.candidate_id,
        "path": str(candidate.path),
        "sha256": sha256_file(candidate.path),
        "source_url": candidate.source_url,
        "source_license": candidate.source_license,
        "role": candidate.role,
        "eligible_for_novelty": candidate.eligible_for_novelty,
        "notes": candidate.notes,
        "parser_warnings": parser_warnings,
        "structure": {
            "n_expanded_crystallographic_sites": len(structure),
            "occupied_atom_count_from_average_occupancies": sum(composition.values()),
            "expected_ordered_atom_count": expected_atoms,
            "volume_angstrom3": float(structure.volume),
            "is_ordered": bool(structure.is_ordered),
            "symmetry_if_ordered": symmetry,
        },
        "composition_check": composition_check,
        "occupational_disorder": {
            "n_disordered_sites": n_disordered,
            "n_mixed_species_sites": n_mixed,
            "n_vacancy_bearing_sites": n_vacancy,
            "n_distinct_disorder_groups": len(disorder),
            "minimum_rationalized_occupancy_denominator_lcm": minimum_multiplier,
            "groups": disorder,
        },
        "route": route,
        "scientific_warnings": scientific_warnings,
        "blockers": blockers,
        "downstream_plan": plan,
    }


def discovery_protocol_summary(protocol: DiscoveryProtocol) -> dict[str, Any]:
    """Return the materialized plan without parsing structures or writing files."""
    return {
        "schema_version": "1.0",
        "study_id": protocol.study_id,
        "title": protocol.title,
        "hypothesis": protocol.hypothesis,
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "root_dir": str(protocol.root_dir),
        "budget": protocol.budget,
        "models": list(protocol.models),
        "stages": protocol.stages,
        "gates": list(protocol.gates),
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "path": str(item.path),
                "role": item.role,
                "eligible_for_novelty": item.eligible_for_novelty,
            }
            for item in protocol.candidates
        ],
        "execution_scope": "CPU structure audit only",
        "gpu_work_started": False,
    }


def build_discovery_audit(path: Path | str) -> dict[str, Any]:
    """Run the zero-GPU audit in memory and return a fingerprinted report."""
    protocol = load_discovery_protocol(path)
    model_environment = _model_environment(protocol.models)
    candidates = [_audit_candidate(item, protocol) for item in protocol.candidates]
    planned_gpu_hours = sum(
        float(item["downstream_plan"]["estimated_gpu_hours"]) for item in candidates
    )
    authorized_gpu_hours = sum(
        float(item["downstream_plan"]["estimated_gpu_hours"])
        for item in candidates
        if item["downstream_plan"]["authorized_now"]
    )
    novelty_inputs = sum(bool(item["eligible_for_novelty"]) for item in candidates)
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "report_kind": "hidden-order-soft-mode-cpu-audit",
        "study_id": protocol.study_id,
        "title": protocol.title,
        "hypothesis": protocol.hypothesis,
        "created_unix_time": time.time(),
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "workflow_path": str(Path(__file__).resolve()),
        "workflow_sha256": sha256_file(__file__),
        "input_manifest": {
            item.candidate_id: {
                "path": str(item.path),
                "sha256": sha256_file(item.path),
            }
            for item in protocol.candidates
        },
        "git": git_state(_ROOT),
        "execution": {
            "completed_stage": "structure_audit",
            "cpu_audit_complete": True,
            "gpu_work_started": False,
            "dft_work_started": False,
            "enabled_stages": sorted(
                name for name, spec in protocol.stages.items() if spec.get("enabled")
            ),
        },
        "budget": {
            **protocol.budget,
            "planned_downstream_gpu_hours": planned_gpu_hours,
            "authorized_gpu_hours_now": authorized_gpu_hours,
            "planned_downstream_within_gpu_budget": planned_gpu_hours
            <= float(protocol.budget["gpu_hours"]),
        },
        "model_environment": model_environment,
        "model_environment_gate_pass": all(
            item["available"] and item["artifact_frozen"] for item in model_environment
        ),
        "gates": list(protocol.gates),
        "candidates": candidates,
        "summary": {
            "n_candidates": len(candidates),
            "n_hidden_order_routes": sum(
                item["route"] == "constrained-hidden-order" for item in candidates
            ),
            "n_soft_mode_prechecks": sum(
                item["route"] == "soft-mode-precheck" for item in candidates
            ),
            "n_ordered_references": sum(
                item["route"] == "ordered-reference-only" for item in candidates
            ),
            "n_blocked": sum(bool(item["blockers"]) for item in candidates),
            "n_novelty_eligible_inputs": novelty_inputs,
        },
        "publication_assessment": {
            "potential_paper_result_available": False,
            "paper_ready": False,
            "current_value": (
                "workflow and input-quality calibration; no new-material claim"
                if novelty_inputs == 0
                else "novelty candidates inventoried but not independently relaxed or verified"
            ),
            "next_release_condition": (
                "add a manually reviewed novelty-eligible candidate manifest, freeze "
                "two model artifacts, and enable only a budget-passing downstream stage"
            ),
        },
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def render_discovery_markdown(report: dict[str, Any]) -> str:
    """Render a compact human audit without inflating scientific claims."""
    summary = report["summary"]
    budget = report["budget"]
    lines = [
        f"# {report['title']}：CPU 结构审计",
        "",
        f"- 研究编号：`{report['study_id']}`",
        f"- 报告指纹：`{report['report_fingerprint']}`",
        f"- 候选数：{summary['n_candidates']}",
        f"- 隐藏有序路线：{summary['n_hidden_order_routes']}",
        f"- 软模预筛路线：{summary['n_soft_mode_prechecks']}",
        f"- 阻塞候选：{summary['n_blocked']}",
        "- 实际 GPU 工作：0 h",
        (
            "- 下游估算："
            f"{budget['planned_downstream_gpu_hours']:.2f} GPU·h / "
            f"{float(budget['gpu_hours']):.2f} GPU·h 上限"
        ),
        "",
        "## 候选审计",
        "",
        "| 候选 | 角色 | 路线 | 平均占位原子数 | 无序位点 | 混占位点 | 组成最大误差 | 状态 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["candidates"]:
        maximum_error = item["composition_check"]["maximum_absolute_error_atoms"]
        error_text = "n/a" if maximum_error is None else f"{maximum_error:.3f}"
        status = "blocked" if item["blockers"] else "audited"
        structure = item["structure"]
        disorder = item["occupational_disorder"]
        lines.append(
            f"| `{item['candidate_id']}` | {item['role']} | {item['route']} | "
            f"{structure['occupied_atom_count_from_average_occupancies']:.3f} | "
            f"{disorder['n_disordered_sites']} | "
            f"{disorder['n_mixed_species_sites']} | {error_text} | {status} |"
        )
    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            report["publication_assessment"]["current_value"] + "。",
            "",
            "本次只运行了 CPU 结构审计；没有启动枚举、GPU 弛豫、声子或 DFT。",
            "因此不存在可投稿结果，也没有把校准材料误标为新颖性候选。",
            "",
            "下一释放条件："
            + report["publication_assessment"]["next_release_condition"]
            + "。",
            "",
            "## 候选警告与阻塞",
            "",
        ]
    )
    for item in report["candidates"]:
        lines.append(f"### `{item['candidate_id']}`")
        lines.append("")
        messages = [
            *(f"解析器：{message}" for message in item["parser_warnings"]),
            *(f"科学警告：{message}" for message in item["scientific_warnings"]),
            *(f"阻塞：{message}" for message in item["blockers"]),
        ]
        if messages:
            lines.extend(f"- {message}" for message in messages)
        else:
            lines.append("- 无。")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _input_manifest(protocol: DiscoveryProtocol) -> dict[str, dict[str, str]]:
    return {
        item.candidate_id: {
            "path": str(item.path),
            "sha256": sha256_file(item.path),
        }
        for item in protocol.candidates
    }


def run_discovery_audit(path: Path | str) -> dict[str, Any]:
    """Write one immutable audit, returning it unchanged on an identical rerun."""
    protocol = load_discovery_protocol(path)
    report_path = protocol.root_dir / "audit.json"
    markdown_path = protocol.root_dir / "audit.md"
    if report_path.exists():
        existing = _read_json(report_path)
        checks = {
            "protocol": existing.get("protocol_sha256") == protocol.protocol_sha256,
            "workflow": existing.get("workflow_sha256") == sha256_file(__file__),
            "inputs": existing.get("input_manifest") == _input_manifest(protocol),
        }
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise RuntimeError(
                "discovery audit provenance changed ("
                + failed
                + "); use a new study_id/root_dir instead of overwriting evidence"
            )
        if not markdown_path.exists():
            raise RuntimeError("audit.json exists but audit.md is missing")
        return existing

    report = build_discovery_audit(protocol.protocol_path)
    atomic_write_json(report_path, report)
    atomic_write_text(markdown_path, render_discovery_markdown(report))
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="validate and print the plan without parsing structures or writing files",
    )
    args = parser.parse_args()
    protocol = load_discovery_protocol(args.protocol)
    if args.list_only:
        print(json.dumps(discovery_protocol_summary(protocol), indent=2))
        return
    report = run_discovery_audit(protocol.protocol_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
