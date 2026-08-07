"""Build doped LLZO cells to match the compositions measured in the literature.

Why this exists: the Materials Project holds exactly one Li7La3Zr2O12 entry and
it is tetragonal (I4_1/acd), the ordered low-conductivity phase. Every
experimental paper in the harvested corpus measures the *cubic* phase, which at
room temperature only exists because a dopant introduces Li vacancies and
disorders the Li sublattice. Comparing a simulated tetragonal cell against a
measured cubic sample would compare two different materials, so the doped cell
has to be constructed.

The construction follows the experimental chemistry:

    Ta5+ / Nb5+ on the Zr4+ site   ->  one Li vacancy per dopant
    Al3+ / Ga3+ on the Li+ site    ->  two Li vacancies per dopant

Charge balance fixes the Li count, so the vacancy concentration is not a free
parameter. Which specific sites are vacated is a choice, and it is made
randomly from a fixed seed: the configurational average is what experiment
measures, and a single hand-picked arrangement would bias the result. The seed
is recorded so any cell can be rebuilt exactly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

# Dopant charge and the site it substitutes, for the aliovalent dopants that
# appear in the harvested records.
DOPANTS: dict[str, tuple[int, str]] = {
    "Ta": (5, "Zr"),
    "Nb": (5, "Zr"),
    "W": (6, "Zr"),
    "Mo": (6, "Zr"),
    "Sb": (5, "Zr"),
    "Al": (3, "Li"),
    "Ga": (3, "Li"),
    "Fe": (3, "Li"),
}

HOST_CHARGE = {"Li": 1, "La": 3, "Zr": 4, "O": -2}


def lithium_vacancies_per_dopant(dopant: str) -> int:
    """Li vacancies created by one substitution, from charge balance alone."""
    if dopant not in DOPANTS:
        raise ValueError(f"unknown dopant {dopant!r}; known: {sorted(DOPANTS)}")
    charge, site = DOPANTS[dopant]
    excess = charge - HOST_CHARGE[site]
    if site == "Li":
        # An Al3+ on a Li+ site both removes that Li and compensates its own
        # excess charge, so it costs three Li in total for two extra vacancies.
        return excess
    return excess


@dataclass
class DopedCell:
    """A constructed composition, with the bookkeeping needed to reproduce it."""

    formula: str
    dopant: str
    dopant_count: int
    lithium_count: int
    lithium_vacancies: int
    n_sites: int
    seed: int
    substituted_sites: list[int] = field(default_factory=list)
    removed_lithium_sites: list[int] = field(default_factory=list)
    net_charge: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def net_charge(structure: "Any", dopant: str | None = None) -> float:
    """Total formal charge; zero means the cell is balanced."""
    charges = dict(HOST_CHARGE)
    if dopant:
        charges[dopant] = DOPANTS[dopant][0]
    total = 0.0
    for species in structure.species:
        symbol = str(species)
        if symbol not in charges:
            raise ValueError(f"no formal charge known for {symbol}")
        total += charges[symbol]
    return total


def make_doped_cell(
    structure: "Any",
    dopant: str,
    count: int,
    *,
    seed: int = 0,
) -> tuple["Any", DopedCell]:
    """Substitute `count` dopants and remove the Li that charge balance requires.

    Returns the new structure and a record of exactly what was changed. The
    input structure is not modified.
    """
    if dopant not in DOPANTS:
        raise ValueError(f"unknown dopant {dopant!r}")
    _charge, host_site = DOPANTS[dopant]
    per_dopant = lithium_vacancies_per_dopant(dopant)

    cell = structure.copy()
    rng = random.Random(seed)

    host_indices = [i for i, s in enumerate(cell.species) if str(s) == host_site]
    if count > len(host_indices):
        raise ValueError(
            f"asked for {count} {dopant} on {len(host_indices)} {host_site} sites"
        )
    chosen = sorted(rng.sample(host_indices, count))
    for index in chosen:
        cell[index] = dopant

    # Remove Li last, and never a site that was just substituted.
    vacancies = per_dopant * count
    lithium = [i for i, s in enumerate(cell.species) if str(s) == "Li"]
    if vacancies > len(lithium):
        raise ValueError(
            f"{dopant}{count} needs {vacancies} Li vacancies but only "
            f"{len(lithium)} Li remain"
        )
    removed = sorted(rng.sample(lithium, vacancies), reverse=True)
    for index in removed:
        cell.remove_sites([index])

    remaining_li = sum(1 for s in cell.species if str(s) == "Li")
    record = DopedCell(
        formula=cell.composition.reduced_formula,
        dopant=dopant,
        dopant_count=count,
        lithium_count=remaining_li,
        lithium_vacancies=vacancies,
        n_sites=len(cell),
        seed=seed,
        substituted_sites=chosen,
        removed_lithium_sites=sorted(removed),
        net_charge=net_charge(cell, dopant),
    )
    return cell, record
