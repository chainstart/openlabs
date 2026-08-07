from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("pymatgen")
pytest.importorskip("scipy")

from matfactory.matched_supercell import (  # noqa: E402
    build_matched_supercell,
    validate_supercell_matrix,
    write_matched_supercell,
)
from matfactory.mlipmd import MDConfig, _load_structure  # noqa: E402

CIF = ROOT / "data/structures/raw/cod_1545083.cif"
MATRIX = [[1, 1, 0], [1, 0, 1], [0, -1, -1]]


def test_matched_conventional_cell_is_an_exact_twofold_replication():
    child, report = build_matched_supercell(
        CIF,
        occupancy_seed=0,
        matrix=MATRIX,
    )
    assert report["size_multiplier"] == 2
    assert report["parent"]["n_sites"] == 94
    assert report["child"]["n_sites"] == 188
    assert child.volume == pytest.approx(2 * report["parent"]["volume_angstrom3"])
    assert child.lattice.a == pytest.approx(12.9481, abs=1e-4)
    assert child.lattice.b == pytest.approx(12.9481, abs=1e-4)
    assert child.lattice.c == pytest.approx(12.9481, abs=1e-4)


@pytest.mark.parametrize(
    "matrix",
    [
        [[1, 0], [0, 1]],
        [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        [[1, 0, 0], [0, 0, 0], [0, 0, 2]],
        [[1.0, 0, 0], [0, 1, 0], [0, 0, 2]],
    ],
)
def test_invalid_or_nonexpanding_supercell_matrix_is_rejected(matrix):
    with pytest.raises(ValueError, match="supercell matrix"):
        validate_supercell_matrix(matrix)


def test_written_artifact_is_immutable_and_loaded_with_provenance(tmp_path):
    prefix = tmp_path / "matched"
    _cif, structure_path, provenance_path = write_matched_supercell(
        CIF,
        prefix,
        occupancy_seed=0,
        matrix=MATRIX,
    )
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    config = MDConfig(
        structure_file=str(structure_path),
        structure_id="derived-COD-1545083-occ00-exact-supercell",
        temperatures=(800,),
    )
    structure, metadata = _load_structure(config)
    assert len(structure) == 188
    assert metadata["derived_structure_provenance"]["size_multiplier"] == 2
    assert (
        metadata["derived_structure_provenance"]["parent_structure_sha256"]
        == provenance["parent"]["structure_sha256"]
    )
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        write_matched_supercell(
            CIF,
            prefix,
            occupancy_seed=0,
            matrix=MATRIX,
        )
