"""Deterministic ordering and provenance tests for experimental structures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("pymatgen")
pytest.importorskip("scipy")

from matfactory.provenance import sha256_file  # noqa: E402
from matfactory.structures import order_llzto_cif  # noqa: E402

CIF = ROOT / "data/structures/raw/cod_1545083.cif"
EXPECTED_CIF_SHA256 = "cbcb4f83b3ee0be0ce7a4e05a9e02bf429f8bb5aee317690678af02939c92ba3"


def test_raw_cif_is_the_pinned_cod_revision():
    assert sha256_file(CIF) == EXPECTED_CIF_SHA256


def test_primitive_ordering_has_exact_neutral_composition():
    structure, record = order_llzto_cif(CIF, seed=7, primitive=True)
    counts = {
        element.symbol: int(amount)
        for element, amount in structure.composition.items()
    }
    assert counts == {"Li": 26, "La": 12, "Zr": 6, "Ta": 2, "O": 48}
    assert len(structure) == 94
    assert structure.is_ordered
    assert record.net_formal_charge == pytest.approx(0.0)
    assert record.source_sha256 == EXPECTED_CIF_SHA256
    assert record.output_min_distance_angstrom >= 1.6


def test_same_seed_reproduces_identical_ordering():
    first, first_record = order_llzto_cif(CIF, seed=11)
    second, second_record = order_llzto_cif(CIF, seed=11)
    assert first_record.output_structure_sha256 == second_record.output_structure_sha256
    assert first == second


def test_conventional_ordering_enables_a_cubic_finite_size_check():
    structure, record = order_llzto_cif(CIF, seed=7, primitive=False)
    counts = {
        element.symbol: int(amount)
        for element, amount in structure.composition.items()
    }
    assert counts == {"Li": 52, "La": 24, "Zr": 12, "Ta": 4, "O": 96}
    assert len(structure) == 188
    assert record.primitive is False
    assert structure.lattice.a == pytest.approx(12.9481, abs=1e-4)
    assert structure.lattice.b == pytest.approx(12.9481, abs=1e-4)
    assert structure.lattice.c == pytest.approx(12.9481, abs=1e-4)


def test_distinct_seeds_sample_distinct_configurations():
    _first, first_record = order_llzto_cif(CIF, seed=1)
    _second, second_record = order_llzto_cif(CIF, seed=2)
    assert first_record.output_structure_sha256 != second_record.output_structure_sha256


def test_incompatible_distance_constraint_is_rejected():
    with pytest.raises(ValueError, match="no Li occupancy"):
        order_llzto_cif(CIF, seed=0, min_li_li_distance_angstrom=2.5)
