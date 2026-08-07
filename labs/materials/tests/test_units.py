"""Regression tests for the unit, header and table-shape bugs that produced
physically impossible values in the first harvest run.

Every fixture below is verbatim markup from a paper in the corpus; the DOI of
each is named so the extraction can be re-checked against the source.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.tables import (  # noqa: E402
    Quantity,
    drop_subheader_rows,
    extract_records,
    extract_unit,
    find_tables,
    header_multiplier,
    is_literature_table,
    normalise,
)

# doi:10.1021/acsami.7b00614 -- the header carries both a milli prefix and, in
# the last column, a bare power of ten.
ACSAMI_HTML = """<table><tr>
<td>y</td><td>Relative density [%]</td><td>&#963;total [mS cm-1]</td>
<td>Ea [eV]</td><td>&#963;Electronic [10-7S cm-1]</td></tr>
<tr><td>0.00</td><td>96.3</td><td>1.12</td><td>0.25</td><td>4.6</td></tr>
<tr><td>0.05</td><td>94.6</td><td>1.62</td><td>0.26</td><td>3.9</td></tr>
</table>"""

# doi:10.3389/fenrg.2016.00028 -- a spanned second header row of temperatures.
FENRG_HTML = """<table><tr>
<td>Ba content x</td><td>Total conductivity &#963;/S cm-1</td><td>Ea/eV</td></tr>
<tr><td>27&#176;C</td><td>50&#176;C</td><td>75&#176;C</td><td>100&#176;C</td></tr>
<tr><td>0</td><td>7.94 &#215; 10-4</td><td>2.70 &#215; 10-3</td>
<td>7.5 &#215; 10-3</td><td>16.0 &#215; 10-3</td><td>0.420</td></tr>
<tr><td>0.05</td><td>8.32 &#215; 10-4</td><td>2.50 &#215; 10-3</td>
<td>7.1 &#215; 10-3</td><td>15.2 &#215; 10-3</td><td>0.410</td></tr>
</table>"""

# doi:10.3390/en16135100 -- a review table compiling other groups' values.
REVIEW_HTML = """<table><tr>
<td>Conductivity (mS/cm)</td><td>Pelletizing Pressure (MPa)</td>
<td>Reference</td><td>Notes</td></tr>
<tr><td>0.22&#8211;3.02</td><td>50&#8211;370</td><td>Doux [15]</td><td>Li6PS5Cl</td></tr>
<tr><td>4.96</td><td>1000</td><td>Yu [21]</td><td>Li6PS5Cl</td></tr>
</table>"""


class TestUnitBoundary:
    """A substring match let "s cm-1" hit inside "ms cm-1", scaling by 1000x."""

    def test_milli_prefix_is_not_shaved_off(self):
        assert extract_unit("σtotal [mS cm-1]") == "ms cm-1"

    def test_plain_unit_still_matches(self):
        assert extract_unit("σ (S cm-1)") == "s cm-1"

    def test_per_metre_is_distinguished_from_per_centimetre(self):
        assert extract_unit("conductivity (S m-1)") == "s m-1"

    def test_millisiemens_converts_to_siemens_per_cm(self):
        got = normalise("total_conductivity", Quantity(1.12, None, "1.12"), "ms cm-1")
        assert got is not None
        assert got.value == pytest.approx(1.12e-3)


class TestHeaderMultiplier:
    def test_bare_power_of_ten_in_header(self):
        assert header_multiplier("σElectronic [10-7S cm-1]") == 1e-7

    def test_explicit_times_ten_in_header(self):
        assert header_multiplier("σ (x 10-4 S/cm)") == 1e-4

    def test_no_power_means_unity(self):
        assert header_multiplier("Ea [eV]") == 1.0

    def test_multiplier_and_unit_compose(self):
        got = normalise("electronic_conductivity", Quantity(4.6, None, "4.6"), "s cm-1", 1e-7)
        assert got is not None
        assert got.value == pytest.approx(4.6e-7)


class TestPlausibility:
    """Out-of-range values are parse failures, so they are dropped, not stored."""

    def test_conductivity_of_one_siemens_per_cm_is_rejected(self):
        # 0.51 with no unit was accepted before; no solid electrolyte is close.
        assert normalise("total_conductivity", Quantity(0.51, None, "0.51"), None) is None

    def test_temperature_mistaken_for_activation_energy_is_rejected(self):
        assert normalise("activation_energy", Quantity(75.0, None, "75"), None) is None

    def test_conductivity_mistaken_for_activation_energy_is_rejected(self):
        assert normalise("activation_energy", Quantity(2.7e-3, None, "2.70e-3"), None) is None

    def test_genuine_activation_energy_survives(self):
        got = normalise("activation_energy", Quantity(0.31, None, "0.31"), "ev")
        assert got is not None and got.value == 0.31

    def test_impossible_relative_density_is_rejected(self):
        assert normalise("relative_density", Quantity(0.51, None, "0.51"), "%") is None


class TestLiteratureTables:
    def test_reference_column_rejects_table(self):
        assert is_literature_table(find_tables(REVIEW_HTML)[0]) is True

    def test_review_table_yields_no_records(self):
        assert extract_records(REVIEW_HTML, doi="10.3390/en16135100") == []

    def test_this_work_row_rejects_table(self):
        html = """<table><tr><td>Sample</td><td>Ea [eV]</td></tr>
        <tr><td>This work</td><td>0.31</td></tr></table>"""
        assert is_literature_table(find_tables(html)[0]) is True

    def test_ordinary_table_is_not_rejected(self):
        assert is_literature_table(find_tables(ACSAMI_HTML)[0]) is False


class TestSubheaderRows:
    def test_temperature_row_is_dropped(self):
        grid = drop_subheader_rows(find_tables(FENRG_HTML)[0])
        assert "27" not in " ".join(grid[1])

    def test_data_rows_survive(self):
        grid = drop_subheader_rows(find_tables(FENRG_HTML)[0])
        assert grid[1][0] == "0"
        assert len(grid) == 3

    def test_ordinary_table_is_untouched(self):
        grid = find_tables(ACSAMI_HTML)[0]
        assert drop_subheader_rows(grid) == grid


class TestSupplements:
    def test_supplement_doi_is_skipped_entirely(self):
        records = extract_records(ACSAMI_HTML, doi="10.1021/acs.iecr.0c05519.s001")
        assert records == []

    def test_parent_doi_is_kept(self):
        assert extract_records(ACSAMI_HTML, doi="10.1021/acsami.7b00614")


class TestAcsamiEndToEnd:
    """The whole-table result for doi:10.1021/acsami.7b00614, table 1."""

    def setup_method(self):
        self.records = extract_records(ACSAMI_HTML, doi="10.1021/acsami.7b00614")

    def test_two_samples(self):
        assert len(self.records) == 2

    def test_numeric_dopant_level_is_qualified_by_its_header(self):
        assert self.records[0].sample == "y=0.00"

    def test_total_conductivity_in_siemens_per_cm(self):
        assert self.records[0].properties["total_conductivity"]["value"] == pytest.approx(1.12e-3)

    def test_electronic_conductivity_uses_header_power(self):
        assert self.records[0].properties["electronic_conductivity"]["value"] == pytest.approx(4.6e-7)

    def test_activation_energy_unchanged(self):
        assert self.records[0].properties["activation_energy"]["value"] == 0.25

    def test_relative_density_kept_as_percent(self):
        assert self.records[0].properties["relative_density"]["value"] == 96.3
