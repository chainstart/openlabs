"""Generate exact-composition orderings from disordered experimental CIFs."""

from __future__ import annotations

import json
import math
import re
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .provenance import (
    atomic_write_json,
    atomic_write_text,
    fingerprint,
    sha256_file,
)
from .structures import structure_fingerprint

_ROOT = Path(__file__).resolve().parents[2]
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VACANCY = "X"


@dataclass(frozen=True)
class OrderingProtocol:
    ordering_id: str
    protocol_path: Path
    protocol_sha256: str
    candidate_protocol: Path
    root_dir: Path
    enabled: bool
    approved_candidate_ids: tuple[str, ...]
    max_orderings_per_candidate: int
    seed_start: int
    max_attempts_multiplier: int
    objective_jitter: float
    minimum_distance_by_species: dict[str, float]
    symmetry_deduplicate: bool
    matcher_stol: float


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def load_ordering_protocol(path: Path | str) -> OrderingProtocol:
    source = Path(path).resolve()
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError("ordering protocol schema_version must be '1.0'")
    ordering_id = payload.get("ordering_id")
    if not isinstance(ordering_id, str) or not _SAFE_ID.fullmatch(ordering_id):
        raise ValueError("ordering_id must be a safe lowercase identifier")

    def integer(field: str, minimum: int, maximum: int) -> int:
        value = payload.get(field)
        if not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
        return value

    objective_jitter = payload.get("objective_jitter")
    if (
        not isinstance(objective_jitter, (int, float))
        or isinstance(objective_jitter, bool)
        or not 0 <= float(objective_jitter) <= 0.1
    ):
        raise ValueError("objective_jitter must be from 0 to 0.1")
    distances = payload.get("minimum_distance_by_species", {})
    if not isinstance(distances, dict) or any(
        not isinstance(element, str)
        or not element
        or not isinstance(distance, (int, float))
        or isinstance(distance, bool)
        or float(distance) <= 0
        for element, distance in distances.items()
    ):
        raise ValueError("minimum_distance_by_species must map elements to distances")
    approved = payload.get("approved_candidate_ids", [])
    if not isinstance(approved, list) or any(
        not isinstance(item, str) or not _SAFE_ID.fullmatch(item) for item in approved
    ):
        raise ValueError("approved_candidate_ids must be safe identifiers")
    if len(set(approved)) != len(approved):
        raise ValueError("approved_candidate_ids contains duplicates")
    matcher_stol = payload.get("matcher_stol", 0.3)
    if (
        not isinstance(matcher_stol, (int, float))
        or isinstance(matcher_stol, bool)
        or not 0 < float(matcher_stol) <= 1
    ):
        raise ValueError("matcher_stol must be from 0 to 1")

    return OrderingProtocol(
        ordering_id=ordering_id,
        protocol_path=source,
        protocol_sha256=sha256_file(source),
        candidate_protocol=_repo_path(str(payload.get("candidate_protocol", ""))),
        root_dir=_repo_path(
            str(payload.get("root_dir", f"runs/orderings/{ordering_id}"))
        ),
        enabled=bool(payload.get("enabled", False)),
        approved_candidate_ids=tuple(approved),
        max_orderings_per_candidate=integer("max_orderings_per_candidate", 1, 128),
        seed_start=integer("seed_start", 0, 2**31 - 1),
        max_attempts_multiplier=integer("max_attempts_multiplier", 1, 100),
        objective_jitter=float(objective_jitter),
        minimum_distance_by_species={
            str(element): float(distance) for element, distance in distances.items()
        },
        symmetry_deduplicate=bool(payload.get("symmetry_deduplicate", True)),
        matcher_stol=float(matcher_stol),
    )


def _symbol(species: Any) -> str:
    element = getattr(species, "element", None)
    if element is not None:
        return str(element.symbol)
    return str(getattr(species, "symbol", species))


def _load_disordered(
    path: Path, occupancy_tolerance: float = 1.05
) -> tuple[Any, list[str]]:
    from pymatgen.io.cif import CifParser

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parser = CifParser(str(path), occupancy_tolerance=occupancy_tolerance)
        structures = parser.parse_structures(primitive=False)
    if len(structures) != 1:
        raise ValueError(f"expected one structure in {path}, found {len(structures)}")
    structure = structures[0]
    if structure.is_ordered:
        raise ValueError(f"{path} is already ordered")
    return structure, list(dict.fromkeys(str(item.message) for item in caught))


def _integer_composition(expected: dict[str, float]) -> dict[str, int]:
    output: dict[str, int] = {}
    for element, amount in expected.items():
        rounded = round(float(amount))
        if not math.isclose(float(amount), rounded, abs_tol=1e-6):
            raise ValueError(
                f"expected cell composition must be integer-valued: {element}={amount}"
            )
        output[str(element)] = int(rounded)
    return output


def _ordered_base_counts(structure: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for site in structure:
        if not site.is_ordered:
            continue
        symbol = _symbol(site.specie)
        counts[symbol] = counts.get(symbol, 0) + 1
    return counts


def _site_options(structure: Any) -> list[dict[str, float] | None]:
    options: list[dict[str, float] | None] = []
    for site in structure:
        if site.is_ordered:
            options.append(None)
            continue
        row = {
            _symbol(species): float(occupancy)
            for species, occupancy in site.species.items()
            if float(occupancy) > 0
        }
        vacancy = 1.0 - sum(row.values())
        if vacancy > 1e-8:
            row[_VACANCY] = vacancy
        if not row:
            raise ValueError("disordered site has no positive occupancy options")
        options.append(row)
    return options


def _build_variables(
    options: list[dict[str, float] | None],
) -> tuple[list[tuple[int, str]], dict[tuple[int, str], int]]:
    variables: list[tuple[int, str]] = []
    for site_index, row in enumerate(options):
        if row is None:
            continue
        variables.extend((site_index, symbol) for symbol in sorted(row))
    return variables, {variable: index for index, variable in enumerate(variables)}


def _assignment_structure(
    average: Any,
    options: list[dict[str, float] | None],
    selected: dict[int, str],
) -> Any:
    from pymatgen.core import Structure

    species: list[str] = []
    coordinates: list[Any] = []
    for site_index, site in enumerate(average):
        if options[site_index] is None:
            symbol = _symbol(site.specie)
        else:
            symbol = selected[site_index]
            if symbol == _VACANCY:
                continue
        species.append(symbol)
        coordinates.append(site.frac_coords)
    return Structure(average.lattice, species, coordinates)


def _minimum_species_distance(structure: Any, symbol: str) -> float | None:
    indices = [
        index for index, site in enumerate(structure) if _symbol(site.specie) == symbol
    ]
    if len(indices) < 2:
        return None
    return min(
        float(structure.get_distance(first, second))
        for offset, first in enumerate(indices)
        for second in indices[offset + 1 :]
    )


def enumerate_exact_orderings(
    structure: Any,
    expected_composition: dict[str, float],
    *,
    max_solutions: int,
    seed_start: int = 0,
    max_attempts_multiplier: int = 10,
    objective_jitter: float = 1e-3,
    minimum_distance_by_species: dict[str, float] | None = None,
    symmetry_deduplicate: bool = True,
    matcher_stol: float = 0.3,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Solve exact site assignments with no-good and optional distance cuts."""
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from scipy.optimize import Bounds, LinearConstraint, milp

    if structure.is_ordered:
        raise ValueError("enumeration requires a disordered average structure")
    if max_solutions < 1:
        raise ValueError("max_solutions must be positive")
    target = _integer_composition(expected_composition)
    base = _ordered_base_counts(structure)
    options = _site_options(structure)
    variables, variable_index = _build_variables(options)
    n_variables = len(variables)
    if not n_variables:
        raise ValueError("no occupational variables found")

    rows: list[np.ndarray] = []
    lower: list[float] = []
    upper: list[float] = []
    for site_index, site_options in enumerate(options):
        if site_options is None:
            continue
        row = np.zeros(n_variables)
        for symbol in site_options:
            row[variable_index[(site_index, symbol)]] = 1.0
        rows.append(row)
        lower.append(1.0)
        upper.append(1.0)

    all_elements = sorted(
        (set(target) | set(base) | {symbol for _site, symbol in variables}) - {_VACANCY}
    )
    for element in all_elements:
        remaining = target.get(element, 0) - base.get(element, 0)
        if remaining < 0:
            raise ValueError(
                f"fixed ordered sites already exceed target count for {element}"
            )
        row = np.zeros(n_variables)
        for variable, index in variable_index.items():
            if variable[1] == element:
                row[index] = 1.0
        if not row.any() and remaining:
            raise ValueError(f"no disordered sites can supply {remaining} {element}")
        rows.append(row)
        lower.append(float(remaining))
        upper.append(float(remaining))

    distance_rules = minimum_distance_by_species or {}
    for element, threshold in sorted(distance_rules.items()):
        candidate_sites = [
            site_index
            for site_index, row in enumerate(options)
            if row is not None and element in row
        ]
        for offset, first in enumerate(candidate_sites):
            for second in candidate_sites[offset + 1 :]:
                if structure.get_distance(first, second) >= float(threshold):
                    continue
                row = np.zeros(n_variables)
                row[variable_index[(first, element)]] = 1.0
                row[variable_index[(second, element)]] = 1.0
                rows.append(row)
                lower.append(-np.inf)
                upper.append(1.0)

    base_objective = np.array(
        [
            -math.log(max(float(options[site][symbol]), 1e-12))
            for site, symbol in variables
        ],
        dtype=float,
    )
    solutions: list[Any] = []
    records: list[dict[str, Any]] = []
    selected_vectors: list[np.ndarray] = []
    matcher = StructureMatcher(
        primitive_cell=False,
        scale=False,
        attempt_supercell=False,
        stol=matcher_stol,
    )
    max_attempts = max_solutions * max_attempts_multiplier
    for attempt in range(max_attempts):
        rng = np.random.default_rng(seed_start + attempt)
        objective = base_objective + rng.uniform(
            -objective_jitter, objective_jitter, n_variables
        )
        attempt_rows = list(rows)
        attempt_lower = list(lower)
        attempt_upper = list(upper)
        for previous in selected_vectors:
            attempt_rows.append(previous.copy())
            attempt_lower.append(-np.inf)
            attempt_upper.append(float(previous.sum() - 1))
        result = milp(
            objective,
            integrality=np.ones(n_variables),
            bounds=Bounds(0.0, 1.0),
            constraints=LinearConstraint(
                np.asarray(attempt_rows), attempt_lower, attempt_upper
            ),
            options={"presolve": True},
        )
        if not result.success or result.x is None:
            break
        selected_vector = (result.x > 0.5).astype(float)
        selected_vectors.append(selected_vector)
        assignment = {
            site_index: symbol
            for (site_index, symbol), value in zip(variables, selected_vector)
            if value > 0.5
        }
        ordered = _assignment_structure(structure, options, assignment)
        actual = {
            str(element): round(amount)
            for element, amount in ordered.composition.get_el_amt_dict().items()
        }
        if actual != target:
            raise AssertionError(f"ordered composition {actual} != target {target}")
        if symmetry_deduplicate and any(
            matcher.fit(ordered, previous) for previous in solutions
        ):
            continue
        minimum_distances = {
            element: _minimum_species_distance(ordered, element)
            for element in distance_rules
        }
        for element, threshold in distance_rules.items():
            measured = minimum_distances[element]
            if measured is not None and measured < threshold - 1e-8:
                raise AssertionError(
                    f"{element} minimum distance {measured} violates {threshold}"
                )
        analyzer = SpacegroupAnalyzer(ordered, symprec=0.1)
        solutions.append(ordered)
        records.append(
            {
                "seed": seed_start + attempt,
                "milp_objective": float(result.fun),
                "assignment": {
                    str(site): symbol for site, symbol in sorted(assignment.items())
                },
                "formula": ordered.composition.formula,
                "n_atoms": len(ordered),
                "space_group_symbol": analyzer.get_space_group_symbol(),
                "space_group_number": analyzer.get_space_group_number(),
                "minimum_distance_by_species": minimum_distances,
                "structure_fingerprint": structure_fingerprint(ordered),
            }
        )
        if len(solutions) >= max_solutions:
            break
    if not solutions:
        raise ValueError("no exact ordering satisfies the frozen constraints")
    return solutions, records


def _candidate_rows(protocol: OrderingProtocol) -> list[dict[str, Any]]:
    payload = _read_json(protocol.candidate_protocol)
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("candidate protocol has no candidate list")
    by_id = {
        str(row.get("candidate_id")): row for row in candidates if isinstance(row, dict)
    }
    missing = sorted(set(protocol.approved_candidate_ids) - by_id.keys())
    if missing:
        raise ValueError("approved candidates not found: " + ", ".join(missing))
    selected: list[dict[str, Any]] = []
    for candidate_id in protocol.approved_candidate_ids:
        row = by_id[candidate_id]
        if row.get("eligible_for_novelty") is not True:
            raise RuntimeError(
                f"candidate {candidate_id} lacks the manual novelty-eligibility release"
            )
        selected.append(row)
    return selected


def ordering_summary(protocol: OrderingProtocol) -> dict[str, Any]:
    return {
        "ordering_id": protocol.ordering_id,
        "protocol_sha256": protocol.protocol_sha256,
        "candidate_protocol": str(protocol.candidate_protocol),
        "enabled": protocol.enabled,
        "approved_candidate_ids": list(protocol.approved_candidate_ids),
        "max_orderings_per_candidate": protocol.max_orderings_per_candidate,
        "gpu_work_started": False,
    }


def run_ordering_campaign(path: Path | str) -> dict[str, Any]:
    """Generate immutable orderings only after two explicit manual releases."""
    from pymatgen.io.cif import CifWriter

    protocol = load_ordering_protocol(path)
    if not protocol.enabled:
        raise RuntimeError("ordering protocol is disabled")
    candidates = _candidate_rows(protocol)
    if not candidates:
        raise RuntimeError("no manually approved candidates were selected")
    state_path = protocol.root_dir / "ordering_manifest.json"
    if state_path.exists():
        state = _read_json(state_path)
        if state.get("protocol_sha256") != protocol.protocol_sha256 or state.get(
            "workflow_sha256"
        ) != sha256_file(__file__):
            raise RuntimeError("ordering evidence changed; use a new ordering_id")
        return state

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        source = _repo_path(str(candidate["path"]))
        expected = candidate.get("expected_composition_per_cell")
        if not isinstance(expected, dict) or not expected:
            raise ValueError(f"candidate {candidate_id} lacks exact composition")
        structure, parser_warnings = _load_disordered(source)
        ordered, records = enumerate_exact_orderings(
            structure,
            {str(key): float(value) for key, value in expected.items()},
            max_solutions=protocol.max_orderings_per_candidate,
            seed_start=protocol.seed_start,
            max_attempts_multiplier=protocol.max_attempts_multiplier,
            objective_jitter=protocol.objective_jitter,
            minimum_distance_by_species=protocol.minimum_distance_by_species,
            symmetry_deduplicate=protocol.symmetry_deduplicate,
            matcher_stol=protocol.matcher_stol,
        )
        candidate_dir = protocol.root_dir / candidate_id
        for index, (item, record) in enumerate(zip(ordered, records)):
            target = candidate_dir / f"ordering-{index:03d}.cif"
            atomic_write_text(target, str(CifWriter(item, symprec=None)))
            record["path"] = str(target)
            record["sha256"] = sha256_file(target)
        results.append(
            {
                "candidate_id": candidate_id,
                "source_path": str(source),
                "source_sha256": sha256_file(source),
                "parser_warnings": parser_warnings,
                "n_requested": protocol.max_orderings_per_candidate,
                "n_generated": len(records),
                "orderings": records,
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "exact-composition-hidden-order-enumeration",
        "ordering_id": protocol.ordering_id,
        "created_unix_time": time.time(),
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "candidate_protocol": str(protocol.candidate_protocol),
        "candidate_protocol_sha256": sha256_file(protocol.candidate_protocol),
        "workflow_path": str(Path(__file__).resolve()),
        "workflow_sha256": sha256_file(__file__),
        "results": results,
        "execution": {"gpu_work_started": False},
        "publication_assessment": {
            "q1_claim_ready": False,
            "reason": "unrelaxed enumerated inputs are not scientific results",
        },
    }
    manifest["content_fingerprint"] = fingerprint(
        {
            "ordering_id": protocol.ordering_id,
            "protocol_sha256": protocol.protocol_sha256,
            "candidate_protocol_sha256": manifest["candidate_protocol_sha256"],
            "results": [
                {
                    "candidate_id": result["candidate_id"],
                    "source_sha256": result["source_sha256"],
                    "n_generated": result["n_generated"],
                    "orderings": [
                        {key: value for key, value in ordering.items() if key != "path"}
                        for ordering in result["orderings"]
                    ],
                }
                for result in results
            ],
        }
    )
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    atomic_write_json(state_path, manifest)
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    protocol = load_ordering_protocol(args.protocol)
    if args.list_only:
        print(json.dumps(ordering_summary(protocol), indent=2))
        return
    print(json.dumps(run_ordering_campaign(protocol.protocol_path), indent=2))


if __name__ == "__main__":
    main()
