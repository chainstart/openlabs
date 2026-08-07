"""Tests for the structural-family classifier.

Ea is only comparable within a family, so a NASICON row leaking into the garnet
distribution is a silent correctness bug, not a cosmetic one. The titles here are
verbatim from harvested papers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.tables import chemistry_family  # noqa: E402

GARNET_TITLE = (
    "Garnet-Type Fast Li-Ion Conductors with High Ionic Conductivities for "
    "All-Solid-State Batteries"
)
NASICON_NA_TITLE = (
    "NASICON Membrane with High Ionic Conductivity Synthesized by "
    "High-Temperature Solid-State Reaction"
)
LATP_TITLE = (
    "Electrochemical Properties of an Sn-Doped LATP Ceramic Electrolyte and "
    "Its Derived Sandwich-Structured Composite"
)


class TestGarnet:
    @pytest.mark.parametrize(
        "text",
        [
            GARNET_TITLE,
            "Investigation of the doping effects of Sr-Ta on Li7La3Zr2O12",
            "Submicron-Sized Nb-Doped Lithium Garnet for High Ionic Conductivity",
            "garnet to hydrogarnet: effect of post synthesis treatment",
            "Empirical decay relationship between ionic conductivity and porosity "
            "of garnet type inorganic solid electrolytes",
            "LLZTO pellet sintered at 1150 C",
        ],
    )
    def test_recognised(self, text):
        assert chemistry_family(text) == "garnet"


class TestNasicon:
    @pytest.mark.parametrize("text", [NASICON_NA_TITLE, "NZSP-1150", "Na3Zr2Si2PO12"])
    def test_sodium_branch(self, text):
        assert chemistry_family(text) == "nasicon-na"

    @pytest.mark.parametrize("text", [LATP_TITLE, "LATP/LB glass ceramic", "LAGP"])
    def test_lithium_branch(self, text):
        assert chemistry_family(text) == "nasicon-li"

    def test_the_two_branches_are_not_conflated(self):
        assert chemistry_family("NZSP") != chemistry_family("LATP")

    def test_specific_li_branch_beats_generic_nasicon_word(self):
        assert (
            chemistry_family("LATP", "NASICON-structured LATP electrolyte")
            == "nasicon-li"
        )


class TestPrecedence:
    def test_garnet_paper_citing_nasicon_stays_garnet(self):
        # A garnet paper routinely name-drops NASICON in its introduction.
        assert chemistry_family(
            "y=0.05", GARNET_TITLE + " compared with NASICON electrolytes"
        ) == "garnet"

    def test_nasicon_paper_is_not_captured_by_a_stray_garnet_word(self):
        assert chemistry_family("NZSP-86", NASICON_NA_TITLE) == "nasicon-na"

    def test_sample_name_and_title_are_both_consulted(self):
        assert chemistry_family("NZSP5-1100", "") == "nasicon-na"


class TestOtherFamilies:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("LLTO perovskite electrolyte", "perovskite"),
            ("Li6PS5Cl argyrodite", "argyrodite"),
            ("Li10GeP2S12 (LGPS)", "thiophosphate"),
            ("thio-LISICON", "thiophosphate"),
        ],
    )
    def test_recognised(self, text, expected):
        assert chemistry_family(text) == expected


class TestUnknown:
    @pytest.mark.parametrize("text", ["", "Sample A", "sintering temperature study"])
    def test_no_marker_gives_unknown(self, text):
        assert chemistry_family(text) == "unknown"

    def test_none_arguments_are_tolerated(self):
        assert chemistry_family(None, GARNET_TITLE) == "garnet"
