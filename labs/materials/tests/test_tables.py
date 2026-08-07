"""Tests for table extraction, using strings taken from real parsed papers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.tables import (  # noqa: E402
    ExtractionStats,
    classify_label,
    extract_records,
    extract_unit,
    merge_by_sample,
    normalise,
    parse_quantity,
    records_from_table,
    table_byte_offsets,
)

# Verbatim from doi:10.1039/d4ma00159a (Mater. Adv., 2024, 5, 5260-5274),
# doc_id ed599c3a..., table 6 in the MinerU parse.
LLZO_TABLE_HTML = (
    "<table><tr><td>Sample</td><td>σtotal(S cm-1)</td><td>Ea(eV)</td>"
    "<td>σelec(S cm-1)</td><td>Relative density (%)</td></tr>"
    "<tr><td>LLZO-Al</td><td>3.72 × 10-4(± 0.44 × 10-4)</td><td>0.31</td>"
    "<td>4.78 × 10-9(± 0.14 × 10-9)</td><td>89</td></tr>"
    "<tr><td>LLZO-Ga</td><td>13.0 × 10-4(± 0.38 × 10-4)</td><td>0.26</td>"
    "<td>1.09 × 10-9(± 0.04 × 10-9)</td><td>94</td></tr>"
    "<tr><td>LLZO-Fe</td><td>11.2 × 10-4(± 0.13 × 10-4)</td><td>0.22</td>"
    "<td>3.90 × 10-9(± 0.07 × 10-9)</td><td>93</td></tr>"
    "<tr><td>LLZO-Ta</td><td>2.38 × 10-4(2) (± 0.12 × 10-4)</td><td>0.37</td>"
    "<td>3.32 × 10-9(± 0.27 × 10-9)</td><td>88</td></tr>"
    "<tr><td>LLZO-Nb</td><td>1.91 × 10-4(± 0.17 × 10-4)</td><td>0.44</td>"
    "<td>2.80 × 10-9(± 015 × 10-9)</td><td>85</td></tr>"
    "<tr><td>LLZO-Sb</td><td>3.41 × 10-4(3) (± 0.14 × 10-4)</td><td>0.41</td>"
    "<td>4.13 × 10-9(± 0.24 × 10-9)</td><td>91</td></tr>"
    "<tr><td>LLZO-W</td><td>5.43 × 10-4(± 0.02 × 10-4)</td><td>0.37</td>"
    "<td>5.04 × 10-9(± 0.19 × 10-9)</td><td>90</td></tr>"
    "<tr><td>LLZO-Mo</td><td>3.03 × 10-4(± 0.06 × 10-4)</td><td>0.36</td>"
    "<td>4.09 × 10-9(± 0.18 × 10-9)</td><td>90</td></tr></table>"
)

# Same paper, table 3: samples across columns instead of down rows.
LLZO_STRUCTURE_HTML = (
    "<table><tr><td>Dopant</td><td>Al</td><td>Ga</td><td>Fe</td><td>Ta</td></tr>"
    "<tr><td>Space group</td><td>Ia3d</td><td>I43d</td><td>I43d</td><td>Ia3d</td></tr>"
    "<tr><td>Lattice parameter [Å]</td><td>12.9711 (1)</td><td>12.9775 (1)</td>"
    "<td>12.9814 (1)</td><td>12.9426 (1)</td></tr></table>"
)


class TestParseQuantity:
    def test_plain_decimal(self):
        q = parse_quantity("0.31")
        assert q is not None and q.value == pytest.approx(0.31)
        assert q.error is None

    def test_scientific_with_error(self):
        q = parse_quantity("3.72 × 10-4(± 0.44 × 10-4)")
        assert q is not None
        assert q.value == pytest.approx(3.72e-4)
        assert q.error == pytest.approx(0.44e-4)

    def test_mantissa_above_ten_is_kept_verbatim(self):
        # "13.0 x 10-4" is 1.3e-3; normalising the mantissa would be wrong.
        q = parse_quantity("13.0 × 10-4(± 0.38 × 10-4)")
        assert q is not None and q.value == pytest.approx(1.30e-3)

    def test_significant_figure_hint_is_ignored(self):
        # The "(2)" is a precision marker, not a value or an error.
        q = parse_quantity("2.38 × 10-4(2) (± 0.12 × 10-4)")
        assert q is not None
        assert q.value == pytest.approx(2.38e-4)
        assert q.error == pytest.approx(0.12e-4)

    def test_ocr_damaged_error_is_discarded_not_guessed(self):
        # "015" lost its decimal point; the value stays, the error is dropped
        # rather than reported as 15e-9 (larger than the value itself).
        q = parse_quantity("2.80 × 10-9(± 015 × 10-9)")
        assert q is not None
        assert q.value == pytest.approx(2.80e-9)
        assert q.error is None

    def test_latex_form(self):
        q = parse_quantity("$1.09 \\times 10^{-9}$")
        assert q is not None and q.value == pytest.approx(1.09e-9)

    def test_unicode_superscript_and_minus(self):
        q = parse_quantity("4.78 × 10⁻⁹")
        assert q is not None and q.value == pytest.approx(4.78e-9)

    def test_e_notation(self):
        q = parse_quantity("1.2e-4")
        assert q is not None and q.value == pytest.approx(1.2e-4)

    def test_range_is_rejected_as_ambiguous(self):
        assert parse_quantity("0.22 to 0.44") is None

    def test_empty_and_placeholders(self):
        for cell in ("", "-", "—", "n/a"):
            assert parse_quantity(cell) is None


class TestLabels:
    def test_classify_specific_before_generic(self):
        assert classify_label("σtotal(S cm-1)") == "total_conductivity"
        assert classify_label("σelec(S cm-1)") == "electronic_conductivity"
        assert classify_label("Ea(eV)") == "activation_energy"
        assert classify_label("Relative density (%)") == "relative_density"
        assert classify_label("Sample") == "sample"

    def test_unit_extraction(self):
        assert extract_unit("σtotal(S cm-1)") == "s cm-1"
        assert extract_unit("Ea(eV)") == "ev"
        assert extract_unit("Relative density (%)") == "%"

    def test_unknown_label(self):
        assert classify_label("Fracture type") is None


class TestNormalise:
    def test_ms_per_cm_converted(self):
        q = parse_quantity("1.3")
        assert q is not None
        out = normalise("ionic_conductivity", q, "ms cm-1")
        assert out is not None and out.value == pytest.approx(1.3e-3)

    def test_mev_converted(self):
        q = parse_quantity("310")
        assert q is not None
        out = normalise("activation_energy", q, "mev")
        assert out is not None and out.value == pytest.approx(0.31)

    def test_unknown_unit_falls_back_to_plausibility(self):
        q = parse_quantity("0.31")
        assert q is not None
        assert normalise("activation_energy", q, None) is not None

    def test_implausible_value_without_unit_is_dropped(self):
        q = parse_quantity("450")
        assert q is not None
        assert normalise("activation_energy", q, None) is None


class TestExtraction:
    def test_real_llzo_table_yields_eight_records(self):
        stats = ExtractionStats()
        records = extract_records(
            LLZO_TABLE_HTML, doc_id="ed599c3a", doi="10.1039/d4ma00159a",
            year=2024, stats=stats,
        )
        assert len(records) == 8
        assert stats.tables_used == 1

        by_sample = {r.sample: r for r in records}
        ga = by_sample["LLZO-Ga"]
        assert ga.properties["activation_energy"]["value"] == pytest.approx(0.26)
        assert ga.properties["total_conductivity"]["value"] == pytest.approx(1.30e-3)
        assert ga.properties["electronic_conductivity"]["value"] == pytest.approx(1.09e-9)
        assert ga.properties["relative_density"]["value"] == pytest.approx(94)

        # Provenance must survive extraction.
        assert ga.doc_id == "ed599c3a"
        assert ga.doi == "10.1039/d4ma00159a"
        assert ga.table_offset is not None
        assert ga.table_offset_unit == "utf8_byte"
        energy = ga.properties["activation_energy"]
        assert energy["unit"] == "eV"
        assert energy["sources"][0]["doc_id"] == "ed599c3a"

    def test_activation_energies_match_published_values(self):
        records = extract_records(LLZO_TABLE_HTML)
        found = {
            r.sample: r.properties["activation_energy"]["value"] for r in records
        }
        expected = {
            "LLZO-Al": 0.31, "LLZO-Ga": 0.26, "LLZO-Fe": 0.22, "LLZO-Ta": 0.37,
            "LLZO-Nb": 0.44, "LLZO-Sb": 0.41, "LLZO-W": 0.37, "LLZO-Mo": 0.36,
        }
        assert found == pytest.approx(expected)

    def test_column_oriented_table_is_detected(self):
        records, status = records_from_table(
            [row for row in _grid(LLZO_STRUCTURE_HTML)]
        )
        assert status == "ok"
        assert {r.sample for r in records} == {"Al", "Ga", "Fe", "Ta"}
        assert all(r.orientation == "column_per_sample" for r in records)
        ga = next(r for r in records if r.sample == "Ga")
        assert ga.properties["space_group"]["value"] == "I43d"
        assert ga.properties["lattice_parameter"]["value"] == pytest.approx(12.9775)

    def test_require_filter_drops_tables_without_the_property(self):
        records = extract_records(LLZO_STRUCTURE_HTML, require=("activation_energy",))
        assert records == []
        records = extract_records(LLZO_STRUCTURE_HTML, require=())
        assert len(records) == 4

    def test_merge_joins_structure_and_property_tables(self):
        combined = extract_records(
            LLZO_TABLE_HTML + LLZO_STRUCTURE_HTML, doc_id="d1", require=()
        )
        merged = merge_by_sample(combined)
        # "LLZO-Ga" and "Ga" normalise to the same sample key.
        ga = next(r for r in merged if _has(r, "Ga"))
        assert "activation_energy" in ga.properties
        assert "space_group" in ga.properties

    def test_no_tables(self):
        assert extract_records("<p>no tables here</p>") == []

    def test_offsets_use_utf8_bytes_not_python_characters(self):
        html = "前缀 µ <table><tr><td>Sample</td><td>Ea/eV</td></tr>" \
               "<tr><td>A</td><td>0.3</td></tr></table>"
        expected = len("前缀 µ ".encode("utf-8"))
        assert table_byte_offsets(html) == [expected]
        record = extract_records(html, doc_id="unicode")[0]
        assert record.table_offset == expected

    def test_measurement_temperature_and_canonical_unit_are_retained(self):
        html = (
            "<table><tr><td>Sample</td><td>Conductivity (S/cm) @ 50 C</td>"
            "<td>Ea/eV</td></tr><tr><td>A</td><td>1e-4</td><td>0.3</td>"
            "</tr></table>"
        )
        record = extract_records(html)[0]
        conductivity = record.properties["ionic_conductivity"]
        assert conductivity["unit"] == "S/cm"
        assert conductivity["measurement_temperature_c"] == pytest.approx(50.0)

    def test_conflicting_join_is_flagged_not_silently_first_wins(self):
        first = extract_records(
            "<table><tr><td>Sample</td><td>Ea/eV</td></tr>"
            "<tr><td>LLZO-Ta</td><td>0.30</td></tr></table>",
            doc_id="d1",
        )[0]
        second = extract_records(
            "<table><tr><td>Sample</td><td>Ea/eV</td></tr>"
            "<tr><td>Ta</td><td>0.40</td></tr></table>",
            doc_id="d1",
        )[0]
        merged = merge_by_sample([first, second])
        assert len(merged) == 1
        assert "activation_energy" not in merged[0].properties
        assert len(merged[0].property_conflicts["activation_energy"]) == 2


def _grid(html: str):
    from matfactory.tables import find_tables

    return find_tables(html)[0]


def _has(record, dopant: str) -> bool:
    return dopant.lower() in record.sample.lower()
