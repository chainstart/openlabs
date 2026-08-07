"""Extract ionic-conductivity records from MinerU-parsed HTML tables.

MinerU emits tables as flat ``<table><tr><td>`` markup with no header
attributes, and the papers themselves disagree on orientation: some list one
sample per row, others put samples across columns (properties as row labels).
Both layouts appear in the same corpus, so orientation is detected rather than
assumed.

Numeric parsing has to survive OCR damage. Real strings seen in the wild:

    "3.72 × 10-4(± 0.44 × 10-4)"   exponent minus, no caret
    "2.38 × 10-4(2) (± 0.12e-4)"   trailing uncertainty digit in parens
    "2.80 × 10-9(± 015 × 10-9)"    dropped decimal point in the error term
    "$1.09 \\times 10^{-9}$"        LaTeX passed through from the PDF

Values that cannot be parsed unambiguously are dropped and counted, never
guessed -- a fabricated number is worse than a missing one.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterable

# --------------------------------------------------------------------- parsing

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")

# Unicode minus, en/em dash, and figure dash all show up as negative signs.
_DASHES = {"−": "-", "–": "-", "—": "-", "‒": "-"}

_MULTIPLY = re.compile(r"\s*(?:×|x|\\times|\*)\s*", re.I)
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")

# "10-4", "10^-4", "10^{-4}", "10 - 4" after the multiplication sign.
_POWER = re.compile(r"10\s*\^?\s*\{?\s*([-+]?\s*\d+)\s*\}?")


def _clean(cell: str) -> str:
    """Strip LaTeX and normalise the characters that break float()."""
    text = cell.strip()
    for source, target in _DASHES.items():
        text = text.replace(source, target)
    text = text.translate(_SUPERSCRIPT)
    text = re.sub(r"\\mathrm|\\text|\\rm|\\,|\\;|\\!|\\ ", " ", text)
    text = text.replace("$", "").replace("\\%", "%")
    text = re.sub(r"\{|\}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class Quantity:
    """A parsed measurement. ``error`` is absolute, in the same unit."""

    value: float
    error: float | None = None
    raw: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "error": self.error, "raw": self.raw}


def parse_quantity(cell: str) -> Quantity | None:
    """Parse one table cell into a number, or return None if ambiguous.

    Handles a scientific-notation mantissa with an optional parenthesised
    uncertainty that may carry its own power of ten.
    """
    text = _clean(cell)
    if not text or text in {"-", "—", "–", "n/a", "na", "nd"}:
        return None

    # Split off a parenthesised error term, ignoring bare "(2)"-style
    # significant-figure markers unless they contain a ± sign.
    error_text = ""
    match = re.search(r"\(([^()]*±[^()]*)\)", text)
    if match:
        error_text = match.group(1)
        text = text[: match.start()] + text[match.end() :]
    text = re.sub(r"\(\s*\d+\s*\)", " ", text)  # drop "(2)" precision hints

    value = _parse_scientific(text)
    if value is None:
        return None

    error = None
    if error_text:
        error = _parse_scientific(error_text.replace("±", " "))
        # A dropped decimal point ("± 015 × 10-9") yields an error larger than
        # the value itself; keep the value, discard the untrustworthy error.
        if error is not None and abs(error) > abs(value) * 2:
            error = None

    return Quantity(value=value, error=error, raw=cell.strip())


def _parse_scientific(text: str) -> float | None:
    """Turn "3.72 × 10-4" or "0.31" into a float."""
    text = text.strip()
    if not text:
        return None

    parts = _MULTIPLY.split(text, maxsplit=1)
    mantissa_text = parts[0]
    exponent = 0

    if len(parts) == 2:
        power = _POWER.search(parts[1])
        if power is None:
            return None
        exponent = int(power.group(1).replace(" ", ""))
    else:
        # Bare "10-4" with no mantissa, or an "e" form like "1.2e-4".
        e_form = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)[eE]([-+]?\d+)", text)
        if e_form:
            return float(e_form.group(1)) * (10 ** int(e_form.group(2)))

    numbers = _NUMBER.findall(mantissa_text)
    if not numbers:
        # "10-4" alone means 1e-4.
        if len(parts) == 1:
            power = _POWER.fullmatch(mantissa_text.strip())
            if power:
                return float(10 ** int(power.group(1).replace(" ", "")))
        return None
    if len(numbers) > 1:
        return None  # a range or a merged cell: too ambiguous to trust

    try:
        return float(numbers[0]) * (10.0**exponent)
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------- table reader


class _TableParser(HTMLParser):
    """Collect ``<table>`` elements as lists of row-lists."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(cell for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def find_tables(html: str) -> list[list[list[str]]]:
    """Every table in a parsed document, as a grid of raw cell strings."""
    parser = _TableParser()
    parser.feed(html)
    return parser.tables


def table_byte_offsets(html: str) -> list[int]:
    """UTF-8 byte offset of each ``<table>``, matching the source API cursor."""
    offsets: list[int] = []
    previous_character = 0
    previous_byte = 0
    for match in re.finditer(r"<table", html, re.I):
        previous_byte += len(
            html[previous_character : match.start()].encode("utf-8")
        )
        offsets.append(previous_byte)
        previous_character = match.start()
    return offsets


def table_char_offsets(html: str) -> list[int]:
    """Backward-compatible name; offsets have always meant API byte offsets."""
    return table_byte_offsets(html)


# ------------------------------------------------------------ property mapping

# Each property maps to regexes matched against a header/label cell. Order
# matters: the first match wins, so the more specific pattern comes first.
PROPERTY_PATTERNS: dict[str, list[str]] = {
    "electronic_conductivity": [
        r"\bsigma\s*_?\s*elec", r"σ\s*elec", r"electronic\s+conductivit",
    ],
    "total_conductivity": [
        r"\bsigma\s*_?\s*total", r"σ\s*total", r"total\s+(?:ionic\s+)?conductivit",
    ],
    "grain_boundary_conductivity": [
        r"\bsigma\s*_?\s*gb", r"σ\s*gb", r"grain[-\s]?boundary\s+conductivit",
    ],
    "bulk_conductivity": [
        r"\bsigma\s*_?\s*(?:bulk|b)\b", r"σ\s*bulk", r"bulk\s+conductivit",
    ],
    "ionic_conductivity": [
        r"\bionic\s+conductivit", r"\bconductivit", r"\bsigma\b", r"σ",
    ],
    "activation_energy": [
        r"\bE\s*_?\s*a\b", r"\bEa\b", r"activation\s+energ",
    ],
    "relative_density": [
        r"relative\s+densit", r"\bdensit.*%",
    ],
    "lattice_parameter": [
        r"lattice\s+(?:parameter|constant)",
    ],
    "space_group": [
        r"space\s+group",
    ],
    "sample": [
        r"^sample", r"^dopant", r"^composition", r"^material", r"^system",
        r"^specimen", r"^abbreviation",
    ],
}

# Units we accept per property, with the factor converting to the canonical
# unit. Conductivity is canonicalised to S/cm, energy to eV.
_UNIT_FACTORS: dict[str, dict[str, float]] = {
    "conductivity": {
        "s cm-1": 1.0, "s/cm": 1.0, "scm-1": 1.0, "s cm": 1.0,
        "ms cm-1": 1e-3, "ms/cm": 1e-3, "mscm-1": 1e-3,
        "s m-1": 1e-2, "s/m": 1e-2, "sm-1": 1e-2,
    },
    "energy": {"ev": 1.0, "mev": 1e-3, "kj mol-1": 0.01036, "kj/mol": 0.01036},
}

_CONDUCTIVITY_PROPERTIES = {
    "total_conductivity", "ionic_conductivity", "bulk_conductivity",
    "grain_boundary_conductivity", "electronic_conductivity",
}


def classify_label(label: str) -> str | None:
    """Map a header or row-label cell onto a canonical property name."""
    text = _clean(label).lower()
    if not text:
        return None
    for prop, patterns in PROPERTY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.I):
                return prop
    return None


# Units sorted longest-first. Plain substring search would let "s cm-1" match
# inside "ms cm-1" and silently scale mS/cm values by 1000x, so both the length
# ordering and the left-boundary check below are load-bearing.
_UNIT_LOOKUP: list[tuple[str, float]] = sorted(
    ((unit, factor) for group in _UNIT_FACTORS.values() for unit, factor in group.items()),
    key=lambda pair: -len(pair[0]),
)


def _unit_at_boundary(candidate: str, unit: str) -> bool:
    """True if `unit` occurs in `candidate` not preceded by a letter, so that
    the "m" of "mS cm-1" cannot be shaved off to leave a bare "S cm-1"."""
    for match in re.finditer(re.escape(unit), candidate):
        before = candidate[match.start() - 1] if match.start() else " "
        if not before.isalpha():
            return True
    return False


def extract_unit(label: str) -> str | None:
    """Pull a unit out of a header like "σtotal(S cm-1)"."""
    text = _clean(label).lower()
    match = re.search(r"[\(\[]([^)\]]*)[\)\]]\s*$", text)
    candidate = match.group(1) if match else text
    candidate = candidate.replace("^", "").strip()
    for unit, _factor in _UNIT_LOOKUP:
        if _unit_at_boundary(candidate, unit):
            return unit
    if "%" in candidate:
        return "%"
    return None


def header_multiplier(label: str) -> float:
    """Headers routinely carry the scale factor instead of the cells, e.g.
    "sigma_Electronic [10-7 S cm-1]" or "sigma (x 10^-4 S/cm)". Such a header
    means the tabulated 4.6 is really 4.6e-7, so the exponent has to be folded
    in or the value lands seven orders of magnitude too high."""
    text = _clean(label).lower()
    inner = re.search(r"[\(\[]([^)\]]*)[\)\]]", text)
    scope = inner.group(1) if inner else text
    power = _POWER.search(scope)
    if not power:
        return 1.0
    return 10.0 ** int(power.group(1).replace(" ", ""))


def _scale(quantity: Quantity, factor: float) -> Quantity:
    return Quantity(
        value=quantity.value * factor,
        error=None if quantity.error is None else quantity.error * factor,
        raw=quantity.raw,
    )


# Physically admissible ranges, applied after scaling. A value outside these is
# a parse failure rather than a discovery, so it is dropped: a fabricated number
# is worse than a missing one.
_PLAUSIBLE = {
    "activation_energy": (0.05, 3.0),
    "relative_density": (30.0, 100.0),
}
# With a unit declared in the header we trust the paper, and allow the full
# range up to the ~1 S/cm reached by beta-alumina at several hundred degrees.
_CONDUCTIVITY_RANGE = (1e-12, 1.0)
# With no unit we are guessing, so the window tightens to what a solid
# electrolyte actually reaches near room temperature. This is what rejects a
# bare "0.51" that is really 0.51 mS/cm.
_CONDUCTIVITY_RANGE_UNITLESS = (1e-12, 1e-1)


def normalise(
    prop: str,
    quantity: Quantity,
    unit: str | None,
    multiplier: float = 1.0,
) -> Quantity | None:
    """Convert to canonical units, or drop the value if it cannot be trusted."""
    if prop in _CONDUCTIVITY_PROPERTIES:
        factors = _UNIT_FACTORS["conductivity"]
    elif prop == "activation_energy":
        factors = _UNIT_FACTORS["energy"]
    else:
        if prop in _PLAUSIBLE:
            low, high = _PLAUSIBLE[prop]
            if not low <= quantity.value * multiplier <= high:
                return None
            return _scale(quantity, multiplier)
        return quantity  # unit-free (space group, lattice parameter)

    if unit is None:
        # No unit in the header: accept only if the magnitude is already
        # physically sensible in the canonical unit.
        scaled = _scale(quantity, multiplier)
        low, high = _PLAUSIBLE.get(prop, _CONDUCTIVITY_RANGE_UNITLESS)
        return scaled if low <= scaled.value <= high else None

    factor = factors.get(unit)
    if factor is None:
        return None
    scaled = _scale(quantity, factor * multiplier)
    low, high = _PLAUSIBLE.get(prop, _CONDUCTIVITY_RANGE)
    return scaled if low <= scaled.value <= high else None


# ------------------------------------------------------------------- extraction


@dataclass
class Record:
    """One sample's measured properties, with provenance back to the source."""

    sample: str
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    doc_id: str | None = None
    doi: str | None = None
    year: int | None = None
    title: str | None = None
    table_index: int | None = None
    table_offset: int | None = None
    table_offset_unit: str = "utf8_byte"
    orientation: str | None = None
    material_class: str | None = None
    chemistry: str | None = None
    property_conflicts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_REFERENCE_HEADER = re.compile(r"^(?:ref\.?|refs\.?|reference|references|source)$", re.I)

# Mirrors sciverse.base_doi's suffix rule; duplicated so this module stays
# independent of the API client.
_SUPPLEMENT_SUFFIX = re.compile(r"\.s\d{2,3}$", re.I)


def is_literature_table(grid: list[list[str]]) -> bool:
    """Reject review tables that compile values from other papers.

    These carry a "Ref." column or a "This work" row, and their cells are often
    ranges ("0.22-3.02"). Harvesting them would attribute another group's
    measurement to the citing paper and double-count it once the cited paper is
    also in the corpus, so the whole table is skipped."""
    header = [_clean(cell) for cell in grid[0]] if grid else []
    if any(_REFERENCE_HEADER.match(cell) for cell in header):
        return True
    for row in grid:
        for cell in row:
            if re.search(r"\bthis\s+(?:work|study)\b", cell, re.I):
                return True
    return False


_TEMPERATURE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*([ck])\b", re.I)
ROOM_TEMPERATURE_C = 25.0


def label_temperature(label: str) -> float | None:
    """Measurement temperature in Celsius, if the header states one."""
    match = _TEMPERATURE.search(_clean(label))
    if not match:
        return None
    value = float(match.group(1))
    return value - 273.15 if match.group(2).lower() == "k" else value


def preferred_columns(labels: dict[int, str], props: dict[int, str]) -> dict[int, str]:
    """Keep one column per property, nearest to room temperature.

    An expanded temperature series offers the same conductivity at 27, 50, 75
    and 100 C. Reported values must be comparable across papers, so the
    room-temperature column wins; without it the whole series would collapse
    onto whichever column happened to come last.
    """
    best: dict[str, tuple[float, int]] = {}
    for index, prop in props.items():
        temperature = label_temperature(labels.get(index, ""))
        distance = abs((temperature if temperature is not None else ROOM_TEMPERATURE_C) - ROOM_TEMPERATURE_C)
        current = best.get(prop)
        if current is None or distance < current[0]:
            best[prop] = (distance, index)
    return {index: prop for prop, (_distance, index) in best.items()}


def _compose_sample(label: str, cell: str) -> str:
    """Doping series tabulate a bare level ("0.05") under a header naming the
    variable ("Ba content x"). The number alone is a meaningless sample id, so
    it is qualified with the header to stay joinable and human-readable."""
    value = _clean(cell)
    label = _clean(label)
    if not label or not value:
        return value
    stripped = value.replace(".", "", 1).replace("-", "", 1)
    if stripped.isdigit() and not classify_label(label):
        return f"{label}={value}"
    return value


_POLYMER_MARKERS = re.compile(
    r"\b(?:PEO|PVA|PVAc|PVDF|PVP|PAN|PMMA|PPC|PCL|PEG|PTFE)\b"
    r"|polymer|copolymer|plasticiz|plasticis|succinonitrile|ionic\s+liquid|gel\b",
    re.I,
)
_CERAMIC_MARKERS = re.compile(
    r"LLZO|LLZ\b|garnet|LATP|LAGP|NASICON|NZSP|LLTO|perovskite|argyrodite"
    r"|Li\d|LGPS|thio-?LISICON|beta-?alumina|Li[0-9.]*La|glass[-\s]?cerami",
    re.I,
)


def material_class(*texts: str) -> str:
    """Label a record "polymer", "ceramic" or "unknown".

    A solid polymer electrolyte and a sintered ceramic conduct by different
    mechanisms and sit an order of magnitude apart in activation energy, so
    pooling them would blur exactly the structure-property relationship this
    corpus exists to measure. They are labelled rather than dropped: the polymer
    rows are still valid data for a different question.

    Polymer markers are tested first because a composite paper mentions both,
    and a PEO-LLZO composite behaves as a polymer electrolyte.
    """
    blob = " ".join(t for t in texts if t)
    if _POLYMER_MARKERS.search(blob):
        return "polymer"
    if _CERAMIC_MARKERS.search(blob):
        return "ceramic"
    return "unknown"


_GARNET_MARKERS = re.compile(
    r"garnet|LLZO|LLZ\b|LLZTO|Li[67](?:\.\d+)?La[23]|hydrogarnet"
    r"|Li[-\s]?stuffed",
    re.I,
)
# NASICON covers both a Na and a Li branch. The Li branch (LATP/LAGP) is a
# phosphate, not a garnet, and its Ea sits in a different range again.
_NASICON_NA_MARKERS = re.compile(r"NZSP|NASICON|Na[13](?:\.\d+)?Zr[23]|Na3Zr2Si2", re.I)
_NASICON_LI_MARKERS = re.compile(r"LATP|LAGP|Li[13](?:\.\d+)?Al[0.]*[GT]", re.I)
_OTHER_FAMILIES: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("perovskite", re.compile(r"LLTO|perovskite|Li[0.]*La[0.]*TiO", re.I)),
    ("argyrodite", re.compile(r"argyrodite|Li6PS5|LPSC?l\b", re.I)),
    ("thiophosphate", re.compile(r"LGPS|thio-?LISICON|Li10GeP2S12", re.I)),
)


def chemistry_family(*texts: str) -> str:
    """Label the structural family: garnet, nasicon-na, nasicon-li, ...

    Activation energy is only comparable within a family. NZSP conducts Na
    through a NASICON framework at 0.13-0.17 eV while garnet LLZO conducts Li at
    0.25-0.45 eV, so pooling them would corrupt any comparison against a Li
    diffusivity computed by MD. The harvest query is deliberately broad, which
    means the family has to be recovered here rather than assumed.

    Garnet is tested first: a garnet paper often cites NASICON in passing, but a
    paper whose samples are named NZSP is not about garnet.
    """
    blob = " ".join(t for t in texts if t)
    # Sample names are the strongest signal, but they arrive concatenated with
    # the title, so order the patterns by specificity instead.
    # LATP/LAGP are the specific Li-NASICON branch. A title often includes the
    # generic word NASICON as well, so testing the generic Na pattern first
    # would mislabel exactly those records.
    if _NASICON_LI_MARKERS.search(blob) and not _GARNET_MARKERS.search(blob):
        return "nasicon-li"
    if _NASICON_NA_MARKERS.search(blob) and not _GARNET_MARKERS.search(blob):
        return "nasicon-na"
    if _GARNET_MARKERS.search(blob):
        return "garnet"
    if _NASICON_LI_MARKERS.search(blob):
        return "nasicon-li"
    if _NASICON_NA_MARKERS.search(blob):
        return "nasicon-na"
    for name, pattern in _OTHER_FAMILIES:
        if pattern.search(blob):
            return name
    return "unknown"


_SUBHEADER_CELL = re.compile(r"^-?\d+(?:\.\d+)?\s*°?\s*[ckf]$", re.I)

CANONICAL_UNITS: dict[str, str] = {
    "electronic_conductivity": "S/cm",
    "total_conductivity": "S/cm",
    "grain_boundary_conductivity": "S/cm",
    "bulk_conductivity": "S/cm",
    "ionic_conductivity": "S/cm",
    "activation_energy": "eV",
    "relative_density": "%",
    "lattice_parameter": "angstrom",
}


def _measurement_payload(prop: str, quantity: Quantity, label: str) -> dict[str, Any]:
    payload = quantity.as_dict()
    unit = CANONICAL_UNITS.get(prop)
    if unit:
        payload["unit"] = unit
    temperature = label_temperature(label)
    if temperature is not None:
        payload["measurement_temperature_c"] = temperature
    return payload


def drop_subheader_rows(grid: list[list[str]]) -> list[list[str]]:
    """Repair a header whose colspan MinerU flattened into a second row.

    A temperature-series table arrives as three ragged rows::

        ["Ba content x", "Total conductivity s/S cm-1", "Ea/eV"]   # 3 cells
        ["27C", "50C", "75C", "100C"]                              # 4 cells
        ["0", "7.94e-4", "2.70e-3", "7.5e-3", "16.0e-3", "0.420"]  # 6 cells

    Simply deleting the temperature row leaves a 3-wide header over 6-wide data,
    so the Ea column is never found and the conductivities are read as one
    column. The spanning cell is instead expanded into one column per
    sub-header, carrying its temperature, which both restores the alignment and
    records the measurement condition.
    """
    if len(grid) < 3:
        return grid
    header, second = grid[0], grid[1]
    subs = [cell for cell in (_clean(c) for c in second) if cell]
    if len(subs) < 2 or not all(_SUBHEADER_CELL.match(cell) for cell in subs):
        return grid

    width = max(len(row) for row in grid[2:])
    span = width - (len(header) - 1)
    if span != len(subs) or span < 2:
        return [grid[0]] + grid[2:]  # cannot align; fall back to dropping it

    # The spanning column is the one that needs `span` sub-labels: find it by
    # testing which position makes the widths add up.
    for pivot, cell in enumerate(header):
        if classify_label(cell) in _CONDUCTIVITY_PROPERTIES:
            break
    else:
        return [grid[0]] + grid[2:]

    expanded = (
        list(header[:pivot])
        + [f"{_clean(header[pivot])} @ {sub}" for sub in subs]
        + list(header[pivot + 1:])
    )
    return [expanded] + grid[2:]


@dataclass
class ExtractionStats:
    tables_seen: int = 0
    tables_used: int = 0
    cells_parsed: int = 0
    cells_dropped: int = 0
    records: int = 0


def _score_orientation(grid: list[list[str]]) -> tuple[str, dict[int, str]]:
    """Decide whether samples run down rows or across columns.

    Returns the orientation and the property found at each index.
    """
    header = grid[0]
    row_labels = [row[0] for row in grid if row]

    col_props = {
        index: prop
        for index, cell in enumerate(header)
        if (prop := classify_label(cell)) and prop != "sample"
    }
    row_props = {
        index: prop
        for index, cell in enumerate(row_labels)
        if (prop := classify_label(cell)) and prop != "sample"
    }

    if len(col_props) >= len(row_props):
        return "row_per_sample", col_props
    return "column_per_sample", row_props


def records_from_table(
    grid: list[list[str]],
    *,
    stats: ExtractionStats | None = None,
) -> tuple[list[Record], str]:
    """Extract records from one table grid."""
    stats = stats or ExtractionStats()
    if len(grid) < 2:
        return [], "too_small"
    if is_literature_table(grid):
        return [], "literature_comparison"
    grid = drop_subheader_rows(grid)

    orientation, props = _score_orientation(grid)
    if not props:
        return [], "no_recognised_properties"
    if orientation == "row_per_sample":
        props = preferred_columns(
            {index: grid[0][index] for index in props if index < len(grid[0])}, props
        )
    else:
        props = preferred_columns(
            {index: grid[index][0] for index in props if index < len(grid)}, props
        )

    records: list[Record] = []

    if orientation == "row_per_sample":
        header = grid[0]
        units = {index: extract_unit(header[index]) for index in props}
        mults = {index: header_multiplier(header[index]) for index in props}
        label = _clean(header[0]) if header else ""
        for row in grid[1:]:
            if not row or not row[0].strip():
                continue
            record = Record(sample=_compose_sample(label, row[0]), orientation=orientation)
            for index, prop in props.items():
                if index >= len(row):
                    continue
                cell = row[index]
                if prop == "space_group":
                    if _clean(cell):
                        record.properties[prop] = {"value": _clean(cell), "raw": cell}
                    continue
                quantity = parse_quantity(cell)
                if quantity is None:
                    if _clean(cell):
                        stats.cells_dropped += 1
                    continue
                normalised = normalise(prop, quantity, units.get(index), mults.get(index, 1.0))
                if normalised is None:
                    stats.cells_dropped += 1
                    continue
                record.properties[prop] = _measurement_payload(
                    prop, normalised, header[index]
                )
                stats.cells_parsed += 1
            if record.properties:
                records.append(record)
    else:
        # Properties are row labels; each remaining column is one sample.
        sample_names = grid[0][1:]
        units = {index: extract_unit(grid[index][0]) for index in props}
        mults = {index: header_multiplier(grid[index][0]) for index in props}
        for column, name in enumerate(sample_names, start=1):
            if not _clean(name):
                continue
            record = Record(sample=_compose_sample(_clean(grid[0][0]), name), orientation=orientation)
            for index, prop in props.items():
                row = grid[index]
                if column >= len(row):
                    continue
                cell = row[column]
                if prop == "space_group":
                    if _clean(cell):
                        record.properties[prop] = {"value": _clean(cell), "raw": cell}
                    continue
                quantity = parse_quantity(cell)
                if quantity is None:
                    if _clean(cell):
                        stats.cells_dropped += 1
                    continue
                normalised = normalise(prop, quantity, units.get(index), mults.get(index, 1.0))
                if normalised is None:
                    stats.cells_dropped += 1
                    continue
                record.properties[prop] = _measurement_payload(
                    prop, normalised, grid[index][0]
                )
                stats.cells_parsed += 1
            if record.properties:
                records.append(record)

    return records, "ok"


def extract_records(
    html: str,
    *,
    doc_id: str | None = None,
    doi: str | None = None,
    year: int | None = None,
    title: str | None = None,
    require: Iterable[str] = ("activation_energy",),
    stats: ExtractionStats | None = None,
) -> list[Record]:
    """Every record in a document that carries at least one required property.

    ``require`` defaults to activation energy because that is the quantity the
    MLIP comparison needs; pass an empty tuple to keep all records.
    """
    stats = stats or ExtractionStats()
    if doi and _SUPPLEMENT_SUFFIX.search(doi.strip()):
        # A ".s001" record is supporting information indexed as its own
        # document. Its tables duplicate or fragment the parent article's, and
        # its numbering columns parse as nonsense sample ids, so skip it whole.
        return []
    required = set(require)
    tables = find_tables(html)
    offsets = table_byte_offsets(html)
    output: list[Record] = []

    for index, grid in enumerate(tables):
        stats.tables_seen += 1
        records, status = records_from_table(grid, stats=stats)
        if status != "ok" or not records:
            continue
        kept = [
            record
            for record in records
            if not required or (required & set(record.properties))
        ]
        if not kept:
            continue
        stats.tables_used += 1
        for record in kept:
            record.doc_id = doc_id
            record.doi = doi
            record.year = year
            record.title = title
            record.table_index = index
            record.table_offset = offsets[index] if index < len(offsets) else None
            record.material_class = material_class(record.sample, title or "")
            record.chemistry = chemistry_family(record.sample, title or "")
            source = {
                "doc_id": doc_id,
                "doi": doi,
                "table_index": index,
                "table_offset": record.table_offset,
                "table_offset_unit": record.table_offset_unit,
            }
            for payload in record.properties.values():
                payload.setdefault("sources", []).append(dict(source))
            output.append(record)
            stats.records += 1

    return output


def merge_by_sample(records: list[Record]) -> list[Record]:
    """Join records for the same sample within a document.

    Structure and property data usually live in separate tables keyed by the
    same dopant or composition label, so joining them is what produces a
    structure-property row.
    """
    merged: dict[tuple[str | None, str], Record] = {}
    for record in records:
        key = (record.doc_id, _sample_key(record.sample))
        if key not in merged:
            merged[key] = Record(
                sample=record.sample,
                properties=dict(record.properties),
                doc_id=record.doc_id,
                doi=record.doi,
                year=record.year,
                title=record.title,
                table_index=record.table_index,
                table_offset=record.table_offset,
                table_offset_unit=record.table_offset_unit,
                orientation=record.orientation,
                material_class=record.material_class,
                chemistry=record.chemistry,
                property_conflicts=deepcopy(record.property_conflicts),
            )
            continue
        target = merged[key]
        for prop, payload in record.properties.items():
            if prop in target.property_conflicts:
                target.property_conflicts[prop].append(deepcopy(payload))
                continue
            if prop not in target.properties:
                target.properties[prop] = deepcopy(payload)
                continue
            existing = target.properties[prop]
            if _same_measurement(existing, payload):
                known = existing.setdefault("sources", [])
                for source in payload.get("sources", []):
                    if source not in known:
                        known.append(deepcopy(source))
                continue
            # Never resolve a disagreement by first-one-wins. Removing the
            # ambiguous property prevents downstream use while both payloads
            # remain available for manual adjudication.
            target.property_conflicts[prop] = [
                deepcopy(existing), deepcopy(payload)
            ]
            del target.properties[prop]
    return list(merged.values())


def _same_measurement(first: dict[str, Any], second: dict[str, Any]) -> bool:
    keys = ("value", "error", "unit", "measurement_temperature_c")
    return all(first.get(key) == second.get(key) for key in keys)


def _sample_key(sample: str) -> str:
    original = "".join(ch if ch.isalnum() else " " for ch in sample.lower())
    original = " ".join(original.split())
    text = re.sub(r"\b(llzo|sample|doped|doping)\b", " ", original)
    key = " ".join(text.split())
    # Generic labels such as "LLZO" used to collapse to an empty key, merging
    # unrelated rows within a document. Preserve the normalized original when
    # stripping boilerplate would erase the identity completely.
    return key or original
