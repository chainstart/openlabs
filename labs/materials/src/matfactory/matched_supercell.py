"""Build an exact, provenance-rich supercell for finite-size MD controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, atomic_write_text, sha256_file
from .structures import order_llzto_cif, structure_fingerprint


def _determinant_3x3(matrix: list[list[int]]) -> int:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def validate_supercell_matrix(matrix: Any) -> tuple[list[list[int]], int]:
    """Return a 3x3 integer matrix and its positive size multiplier."""
    if not isinstance(matrix, (list, tuple)) or len(matrix) != 3:
        raise ValueError("supercell matrix must have three rows")
    normalized: list[list[int]] = []
    for row in matrix:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ValueError("supercell matrix must be 3x3")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in row):
            raise ValueError("supercell matrix entries must be integers")
        normalized.append([int(value) for value in row])
    determinant = _determinant_3x3(normalized)
    if determinant <= 1:
        raise ValueError("supercell matrix must have a positive determinant above one")
    return normalized, determinant


def build_matched_supercell(
    cif_path: Path | str,
    *,
    occupancy_seed: int,
    matrix: Any,
) -> tuple[Any, dict[str, Any]]:
    """Replicate one ordered primitive realization without re-sampling sites."""
    source_argument = Path(cif_path)
    source = source_argument.resolve()
    normalized, determinant = validate_supercell_matrix(matrix)
    parent, ordering = order_llzto_cif(
        source,
        seed=occupancy_seed,
        primitive=True,
    )
    parent_fingerprint = structure_fingerprint(parent)
    child = parent.copy()
    child.make_supercell(normalized)
    if len(child) != determinant * len(parent):
        raise AssertionError("supercell site count does not match matrix determinant")
    if structure_fingerprint(parent) != parent_fingerprint:
        raise AssertionError("supercell construction mutated its parent structure")
    ordering_payload = ordering.as_dict()
    ordering_payload["source_path"] = str(source_argument)
    report = {
        "schema_version": "1.0",
        "artifact_kind": "exact-periodic-supercell",
        "claim_role": "matched finite-size sensitivity control",
        "source_cif_path": str(source_argument),
        "source_cif_sha256": sha256_file(source),
        "occupancy_seed": int(occupancy_seed),
        "occupancy_ordering": ordering_payload,
        "parent": {
            "n_sites": len(parent),
            "volume_angstrom3": float(parent.volume),
            "structure_sha256": parent_fingerprint,
        },
        "supercell_matrix": normalized,
        "size_multiplier": determinant,
        "child": {
            "n_sites": len(child),
            "volume_angstrom3": float(child.volume),
            "structure_sha256": structure_fingerprint(child),
        },
        "construction_rule": (
            "Order the 94-atom primitive occupancy realization once, then apply "
            "the recorded integer lattice transform. No Li or Zr/Ta site is "
            "re-sampled in the 188-atom control."
        ),
    }
    return child, report


def write_matched_supercell(
    cif_path: Path | str,
    output_prefix: Path | str,
    *,
    occupancy_seed: int,
    matrix: Any,
) -> tuple[Path, Path, Path]:
    """Write an immutable CIF, pymatgen JSON, and provenance record."""
    from pymatgen.io.cif import CifWriter

    prefix = Path(output_prefix)
    cif_output = Path(f"{prefix}.cif")
    structure_output = Path(f"{prefix}.structure.json")
    provenance_output = Path(f"{prefix}.provenance.json")
    destinations = (cif_output, structure_output, provenance_output)
    existing = [path for path in destinations if path.exists()]
    if existing:
        raise RuntimeError(
            "refusing to overwrite matched-supercell artifact: "
            + ", ".join(str(path) for path in existing)
        )
    child, report = build_matched_supercell(
        cif_path,
        occupancy_seed=occupancy_seed,
        matrix=matrix,
    )
    atomic_write_text(cif_output, str(CifWriter(child, symprec=None)))
    atomic_write_json(structure_output, child.as_dict())
    report["outputs"] = {
        "cif_path": str(cif_output),
        "cif_sha256": sha256_file(cif_output),
        "structure_json_path": str(structure_output),
        "structure_json_sha256": sha256_file(structure_output),
    }
    project_root = Path(__file__).resolve().parents[2]
    report["implementation_path"] = str(Path(__file__).resolve().relative_to(project_root))
    report["implementation_sha256"] = sha256_file(__file__)
    atomic_write_json(provenance_output, report)
    return cif_output, structure_output, provenance_output


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cif", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--occupancy-seed", type=int, required=True)
    parser.add_argument(
        "--matrix-json",
        required=True,
        help="3x3 integer supercell matrix encoded as JSON",
    )
    args = parser.parse_args()
    outputs = write_matched_supercell(
        args.cif,
        args.out_prefix,
        occupancy_seed=args.occupancy_seed,
        matrix=json.loads(args.matrix_json),
    )
    print("\n".join(str(path) for path in outputs))


if __name__ == "__main__":
    main()
