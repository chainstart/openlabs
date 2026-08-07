from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from ase.build import bulk
from ase.calculators.emt import EMT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.soft_modes import (
    finite_displacement_phonons,
    load_soft_mode_protocol,
    run_soft_mode_campaign,
    select_soft_modes,
)

PROTOCOL = ROOT / "analysis/protocols/hidden_order_soft_modes_v1.json"


def test_phonopy_finite_displacement_path_with_open_emt():
    atoms = bulk("Al", "fcc", a=4.05, cubic=True)
    phonon, report = finite_displacement_phonons(
        atoms,
        EMT(),
        supercell_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        displacement_distance_angstrom=0.01,
        plus_minus_displacements=True,
        mesh=(2, 2, 2),
        threshold_thz=-0.3,
        max_modes=3,
    )
    assert report["n_displacements"] > 0
    assert report["n_irreducible_qpoints"] > 0
    assert np.asarray(phonon.force_constants).shape == (4, 4, 3, 3)
    assert report["minimum_frequency_thz"] > -0.3


def test_soft_mode_selector_is_thresholded_and_sorted():
    rows = select_soft_modes(
        np.array([[0, 0, 0], [0.5, 0, 0]]),
        np.array([[-0.2, 1.0], [-1.2, -0.5]]),
        np.array([1, 3]),
        threshold_thz=-0.3,
        max_modes=2,
    )
    assert [row["frequency_thz"] for row in rows] == [-1.2, -0.5]
    assert rows[0]["mesh_weight"] == 3


def test_frozen_soft_mode_protocol_is_disabled():
    protocol = load_soft_mode_protocol(PROTOCOL)
    assert not protocol.enabled
    assert protocol.dynamical_model_id == "mace-mp-0-small"
    with pytest.raises(RuntimeError, match="disabled"):
        run_soft_mode_campaign(PROTOCOL)
