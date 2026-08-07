"""Tests for doped-cell construction.

Charge neutrality is the property that matters: an unbalanced cell is not the
material the experiment measured, and CHGNet will happily run on it and return a
confident wrong answer. These tests use a synthetic LLZO-stoichiometry cell so
they need no network access.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("pymatgen")

from matfactory.doping import (  # noqa: E402
    lithium_vacancies_per_dopant,
    make_doped_cell,
    net_charge,
)


def _llzo_cell():
    """A Li7La3Zr2O12 cell with the right stoichiometry, geometry aside."""
    from pymatgen.core import Lattice, Structure

    species = ["Li"] * 28 + ["La"] * 12 + ["Zr"] * 8 + ["O"] * 48
    n = len(species)
    coords = [[(i % 4) / 4, ((i // 4) % 4) / 4, (i // 16) / (n // 16 + 1)] for i in range(n)]
    return Structure(Lattice.cubic(13.0), species, coords)


class TestChargeBalance:
    def test_undoped_cell_is_neutral(self):
        assert net_charge(_llzo_cell()) == pytest.approx(0.0)

    def test_pentavalent_dopant_costs_one_lithium(self):
        assert lithium_vacancies_per_dopant("Ta") == 1

    def test_hexavalent_dopant_costs_two_lithium(self):
        assert lithium_vacancies_per_dopant("W") == 2

    def test_trivalent_on_lithium_site_costs_two(self):
        assert lithium_vacancies_per_dopant("Al") == 2

    def test_unknown_dopant_is_rejected(self):
        with pytest.raises(ValueError):
            lithium_vacancies_per_dopant("Xx")


class TestDopedCells:
    @pytest.mark.parametrize("dopant,count", [
        ("Ta", 1), ("Ta", 4), ("Nb", 2), ("W", 2), ("Al", 2), ("Ga", 3),
    ])
    def test_constructed_cell_is_charge_neutral(self, dopant, count):
        cell, record = make_doped_cell(_llzo_cell(), dopant, count)
        assert record.net_charge == pytest.approx(0.0), (
            f"{dopant}{count} left net charge {record.net_charge}"
        )
        assert net_charge(cell, dopant) == pytest.approx(0.0)

    def test_lithium_count_follows_charge_balance(self):
        _cell, record = make_doped_cell(_llzo_cell(), "Ta", 4)
        assert record.lithium_vacancies == 4
        assert record.lithium_count == 28 - 4

    def test_dopant_actually_replaces_the_host_species(self):
        cell, record = make_doped_cell(_llzo_cell(), "Ta", 3)
        assert sum(1 for s in cell.species if str(s) == "Ta") == 3
        assert sum(1 for s in cell.species if str(s) == "Zr") == 8 - 3
        assert record.dopant_count == 3

    def test_same_seed_reproduces_the_same_cell(self):
        first, record_a = make_doped_cell(_llzo_cell(), "Ta", 4, seed=7)
        second, record_b = make_doped_cell(_llzo_cell(), "Ta", 4, seed=7)
        assert record_a.substituted_sites == record_b.substituted_sites
        assert record_a.removed_lithium_sites == record_b.removed_lithium_sites
        assert [str(s) for s in first.species] == [str(s) for s in second.species]

    def test_different_seeds_give_different_arrangements(self):
        _a, record_a = make_doped_cell(_llzo_cell(), "Ta", 4, seed=1)
        _b, record_b = make_doped_cell(_llzo_cell(), "Ta", 4, seed=2)
        assert record_a.substituted_sites != record_b.substituted_sites

    def test_input_structure_is_not_mutated(self):
        cell = _llzo_cell()
        before = [str(s) for s in cell.species]
        make_doped_cell(cell, "Ta", 4)
        assert [str(s) for s in cell.species] == before

    def test_site_count_drops_by_the_vacancy_count(self):
        cell, record = make_doped_cell(_llzo_cell(), "W", 2)
        assert len(cell) == 96 - 4
        assert record.n_sites == 96 - 4

    def test_overdoping_beyond_available_sites_is_rejected(self):
        with pytest.raises(ValueError, match="Zr sites"):
            make_doped_cell(_llzo_cell(), "Ta", 9)
