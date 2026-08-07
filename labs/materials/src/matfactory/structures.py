"""Fetch crystal structures from OPTIMADE providers.

OPTIMADE is used rather than a provider's native API because it needs no
credentials and exposes the same records through one query language, so a
structure source can be swapped without touching calling code.

Structures obtained here are *inputs* to the simulation, never labels: the
Materials Project entries are part of CHGNet's training set, so using their
energies as validation targets would leak. Experimental values from the
literature are the only labels used.
"""

from __future__ import annotations

import json
import math
import time
import warnings
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, atomic_write_text, canonical_json, sha256_bytes, sha256_file

PROVIDERS = {
    "mp": "https://optimade.materialsproject.org/v1",
    "alexandria": "https://alexandria.icams.rub.de/pbe/v1",
    "oqmd": "https://oqmd.org/optimade/v1",
}

# OPTIMADE requires chemical_formula_reduced in Hill-like alphabetical order,
# so the conventional "Li7La3Zr2O12" finds nothing and must be re-sorted.
USER_AGENT = "matfactory/0.1 (materials literature agent)"


def alphabetical_formula(formula: str) -> str:
    """Reorder "Li7La3Zr2O12" into the alphabetical form OPTIMADE indexes."""
    import re

    parts = re.findall(r"([A-Z][a-z]?)(\d*)", formula)
    terms = [(el, count) for el, count in parts if el]
    terms.sort(key=lambda pair: pair[0])
    return "".join(f"{el}{count}" for el, count in terms)


def _get(url: str, *, timeout: float = 90.0, retries: int = 3) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # network, JSON, or provider error
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"OPTIMADE request failed: {url}: {last}")


def search(
    formula: str,
    *,
    provider: str = "mp",
    limit: int = 5,
    cache_dir: Path | str | None = "cache/optimade",
) -> list[dict[str, Any]]:
    """Structures whose reduced formula matches, newest API version first."""
    query = alphabetical_formula(formula)
    base = PROVIDERS[provider]
    url = (
        f"{base}/structures?filter="
        + urllib.parse.quote(f'chemical_formula_reduced="{query}"')
        + f"&page_limit={limit}"
        + "&response_fields=lattice_vectors,cartesian_site_positions,species,"
        + "species_at_sites,nsites,chemical_formula_reduced"
    )

    cache_path = None
    if cache_dir:
        cache_path = Path(cache_dir) / f"{provider}-{query}-{limit}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))["data"]

    payload = _get(url)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(cache_path, payload, indent=None)
    return payload.get("data", [])


def to_pymatgen(entry: dict[str, Any]):
    """Convert one OPTIMADE entry into a pymatgen Structure.

    Disordered entries are rejected. Choosing the majority species changes the
    composition, charge balance, and mobile-ion topology; an ordered realization
    must instead be generated with explicit occupancy constraints.
    """
    from pymatgen.core import Structure

    attributes = entry["attributes"]
    lattice = attributes["lattice_vectors"]
    coords = attributes["cartesian_site_positions"]
    species_at_sites = attributes["species_at_sites"]
    species_map = {
        item["name"]: item for item in attributes.get("species", [])
    }

    symbols: list[str] = []
    for name in species_at_sites:
        spec = species_map.get(name, {})
        elements = spec.get("chemical_symbols", [name])
        fractions = spec.get("concentration", [1.0] * len(elements))
        occupied = [
            (element, float(fraction))
            for element, fraction in zip(elements, fractions)
            if element not in {"vacancy", "X"} and float(fraction) > 0
        ]
        total = sum(fraction for _element, fraction in occupied)
        if len(occupied) != 1 or not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(
                f"OPTIMADE entry {entry.get('id')} contains disordered site "
                f"{name!r}; generate an explicit ordered configuration"
            )
        symbols.append(occupied[0][0])

    return Structure(
        lattice=lattice,
        species=symbols,
        coords=coords,
        coords_are_cartesian=True,
    )


def fetch_structure(
    formula: str,
    *,
    provider: str = "mp",
    index: int = 0,
    structure_id: str | None = None,
):
    """A matching ordered structure, optionally pinned to an exact record id."""
    entries = search(formula, provider=provider)
    if not entries:
        raise LookupError(f"no OPTIMADE structure for {formula} at {provider}")
    if structure_id is not None:
        try:
            entry = next(entry for entry in entries if entry.get("id") == structure_id)
        except StopIteration as exc:
            raise LookupError(
                f"OPTIMADE structure {structure_id!r} not returned for {formula}"
            ) from exc
    else:
        try:
            entry = entries[index]
        except IndexError as exc:
            raise LookupError(
                f"structure index {index} out of range for {len(entries)} result(s)"
            ) from exc
    return to_pymatgen(entry), entry["id"]


@dataclass
class OrderedStructureRecord:
    """Provenance for one occupancy-constrained realization of a CIF."""

    source_path: str
    source_sha256: str
    source_id: str
    source_url: str
    source_space_group: int
    source_parser_warnings: list[str]
    primitive: bool
    seed: int
    min_li_li_distance_angstrom: float
    target_counts: dict[str, int]
    selected_li_site_indices: list[int] = field(default_factory=list)
    selected_ta_site_indices: list[int] = field(default_factory=list)
    output_formula: str = ""
    output_sites: int = 0
    output_structure_sha256: str = ""
    output_min_distance_angstrom: float = 0.0
    net_formal_charge: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def structure_fingerprint(structure: "Any") -> str:
    """Hash lattice, species, coordinates, and site properties."""
    return sha256_bytes(canonical_json(structure.as_dict()).encode("utf-8"))


def load_cif_preserving_disorder(
    path: Path | str, *, primitive: bool = False
) -> tuple[Any, list[str]]:
    """Parse a CIF at a tolerant occupancy threshold and retain all warnings."""
    from pymatgen.io.cif import CifParser

    parser = CifParser(str(path), occupancy_tolerance=2.0)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        structures = parser.parse_structures(primitive=False)
    if len(structures) != 1:
        raise ValueError(f"expected one structure in {path}, found {len(structures)}")
    structure = structures[0]
    if primitive:
        structure = structure.get_primitive_structure(tolerance=0.1)
    messages = list(dict.fromkeys(str(item.message) for item in caught))
    return structure, messages


def load_disordered_cif(path: Path | str, *, primitive: bool = True):
    """Load a diffraction CIF without inventing atoms for partial occupancies."""
    structure, _messages = load_cif_preserving_disorder(path, primitive=primitive)
    if structure.is_ordered:
        raise ValueError(f"{path} is already ordered; no occupancy sampling needed")
    return structure


def order_llzto_cif(
    path: Path | str,
    *,
    seed: int,
    primitive: bool = True,
    min_li_li_distance_angstrom: float = 1.6,
) -> tuple["Any", OrderedStructureRecord]:
    """Order COD 1545083 at exact Li6.5La3Zr1.5Ta0.5O12 stoichiometry.

    The diffraction model exposes partially occupied Li sites and mixed Zr/Ta
    sites. A binary integer program chooses the exact number of Li atoms while
    forbidding simultaneous occupation of experimentally split sites closer
    than ``min_li_li_distance_angstrom``. Its likelihood objective respects the
    refined occupancies; a seeded jitter samples distinct, reproducible members
    of the degenerate solution set.
    """
    import numpy as np
    from pymatgen.core import Structure
    from scipy.optimize import Bounds, LinearConstraint, milp

    source = Path(path)
    structure, parser_warnings = load_cif_preserving_disorder(
        source, primitive=primitive
    )
    if structure.is_ordered:
        raise ValueError(f"{path} is already ordered; no occupancy sampling needed")
    oxygen = round(float(structure.composition.get("O", 0)))
    if oxygen <= 0 or oxygen % 12:
        raise ValueError(f"expected an LLZTO cell with O count divisible by 12, got {oxygen}")
    formula_units = oxygen // 12
    targets = {
        "Li": int(round(6.5 * formula_units)),
        "La": 3 * formula_units,
        "Zr": int(round(1.5 * formula_units)),
        "Ta": int(round(0.5 * formula_units)),
        "O": 12 * formula_units,
    }

    li_candidates: list[int] = []
    li_occupancies: list[float] = []
    transition_candidates: list[int] = []
    for index, site in enumerate(structure):
        elements = {element.symbol for element in site.species}
        if elements == {"Li"} and not site.is_ordered:
            li_candidates.append(index)
            li_occupancies.append(float(site.species.get("Li")))
        elif elements == {"Zr", "Ta"}:
            transition_candidates.append(index)
        elif not site.is_ordered:
            raise ValueError(
                f"unsupported disordered site {index}: {site.species}"
            )

    if targets["Li"] > len(li_candidates):
        raise ValueError("more Li requested than partial-occupancy candidate sites")
    if targets["Ta"] > len(transition_candidates):
        raise ValueError("more Ta requested than mixed Zr/Ta sites")

    rng = np.random.default_rng(seed)
    objective = np.array(
        [-math.log(p / (1.0 - p)) for p in li_occupancies], dtype=float
    )
    objective += rng.uniform(-1e-5, 1e-5, size=objective.size)
    rows: list[Any] = []
    lower: list[float] = []
    upper: list[float] = []
    for first, site_a in enumerate(li_candidates):
        for second in range(first + 1, len(li_candidates)):
            site_b = li_candidates[second]
            if structure.get_distance(site_a, site_b) < min_li_li_distance_angstrom:
                row = np.zeros(len(li_candidates))
                row[first] = 1.0
                row[second] = 1.0
                rows.append(row)
                lower.append(-np.inf)
                upper.append(1.0)
    rows.append(np.ones(len(li_candidates)))
    lower.append(float(targets["Li"]))
    upper.append(float(targets["Li"]))
    result = milp(
        objective,
        integrality=np.ones(len(li_candidates)),
        bounds=Bounds(0.0, 1.0),
        constraints=LinearConstraint(np.asarray(rows), lower, upper),
        options={"presolve": True},
    )
    if not result.success or result.x is None:
        raise ValueError(
            "no Li occupancy satisfies the requested count and minimum distance: "
            f"{result.message}"
        )
    selected_li = {
        li_candidates[index]
        for index, value in enumerate(result.x)
        if value > 0.5
    }
    selected_ta = set(
        int(index)
        for index in rng.choice(
            transition_candidates, size=targets["Ta"], replace=False
        )
    )

    species: list[str] = []
    coordinates: list[Any] = []
    for index, site in enumerate(structure):
        elements = {element.symbol for element in site.species}
        if index in li_candidates:
            if index not in selected_li:
                continue
            symbol = "Li"
        elif index in transition_candidates:
            symbol = "Ta" if index in selected_ta else "Zr"
        elif site.is_ordered:
            symbol = site.specie.symbol
        else:  # guarded above, kept defensive for future CIFs
            raise ValueError(f"could not order site {index}: {site.species}")
        species.append(symbol)
        coordinates.append(site.frac_coords)

    ordered = Structure(structure.lattice, species, coordinates)
    actual = {element.symbol: int(round(amount)) for element, amount in ordered.composition.items()}
    if actual != targets:
        raise AssertionError(f"ordered composition {actual} does not match target {targets}")
    matrix = np.asarray(ordered.distance_matrix)
    np.fill_diagonal(matrix, np.inf)
    output_minimum = float(matrix.min())
    charge = (
        actual["Li"] + 3 * actual["La"] + 4 * actual["Zr"]
        + 5 * actual["Ta"] - 2 * actual["O"]
    )
    record = OrderedStructureRecord(
        source_path=str(source),
        source_sha256=sha256_file(source),
        source_id="COD-1545083",
        source_url="https://www.crystallography.net/cod/1545083.html",
        source_space_group=230,
        source_parser_warnings=parser_warnings,
        primitive=primitive,
        seed=seed,
        min_li_li_distance_angstrom=min_li_li_distance_angstrom,
        target_counts=targets,
        selected_li_site_indices=sorted(selected_li),
        selected_ta_site_indices=sorted(selected_ta),
        output_formula=ordered.composition.reduced_formula,
        output_sites=len(ordered),
        output_structure_sha256=structure_fingerprint(ordered),
        output_min_distance_angstrom=output_minimum,
        net_formal_charge=float(charge),
    )
    return ordered, record


def write_structure_bundle(
    structure: "Any", record: OrderedStructureRecord, output_prefix: Path | str
) -> tuple[Path, Path, Path]:
    """Freeze an ordered structure as CIF, pymatgen JSON, and provenance JSON."""
    from pymatgen.io.cif import CifWriter

    prefix = Path(output_prefix)
    cif_path = Path(f"{prefix}.cif")
    structure_path = Path(f"{prefix}.structure.json")
    record_path = Path(f"{prefix}.provenance.json")
    atomic_write_text(cif_path, str(CifWriter(structure, symprec=None)))
    atomic_write_json(structure_path, structure.as_dict())
    atomic_write_json(record_path, record.as_dict())
    return cif_path, structure_path, record_path
