from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("pymatgen")

from matfactory.mechanisms import (  # noqa: E402
    JumpEvent,
    assign_fractional_positions,
    build_llzto_site_model,
    extract_dwells_and_jumps,
    null_corrected_string_statistics,
    reverse_jump_statistics,
    string_statistics,
)


def test_pinned_llzto_model_collapses_60_candidates_to_36_basins():
    model = build_llzto_site_model(ROOT / "data/structures/raw/cod_1545083.cif")
    assert model["n_candidate_positions"] == 60
    assert model["n_basins"] == 36
    assert model["site_type_counts"] == {
        "octahedral-96h-pair": 24,
        "tetrahedral-24d": 12,
    }
    coordination = {
        row["site_type"]: row["oxygen_coordination"] for row in model["basins"]
    }
    assert coordination == {
        "octahedral-96h-pair": 6,
        "tetrahedral-24d": 4,
    }


def test_site_model_fingerprint_is_independent_of_python_hash_seed():
    script = (
        "from matfactory.mechanisms import build_llzto_site_model; "
        "print(build_llzto_site_model('data/structures/raw/cod_1545083.cif')"
        "['site_model_fingerprint'])"
    )
    fingerprints = []
    for seed in ("1", "901"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(ROOT / "src")
        fingerprints.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=environment,
                text=True,
            ).strip()
        )
    assert len(set(fingerprints)) == 1


def test_site_assignment_uses_periodic_minimum_image():
    assignment, distance = assign_fractional_positions(
        np.array([[0.02, 0.5, 0.5]]),
        np.eye(3) * 5.0,
        np.array([[0.98, 0.5, 0.5], [0.5, 0.5, 0.5]]),
        max_distance_angstrom=0.3,
    )
    assert assignment.tolist() == [0]
    assert distance.tolist() == pytest.approx([0.2])


def test_site_assignment_finds_true_minimum_image_in_a_skewed_cell():
    assignment, distance = assign_fractional_positions(
        np.array([[0.49, 0.49, 0.5]]),
        np.array([[5.0, 0.0, 0.0], [4.5, 0.5, 0.0], [0.0, 0.0, 5.0]]),
        np.array([[0.0, 0.0, 0.5]]),
        max_distance_angstrom=0.4,
    )
    assert assignment.tolist() == [0]
    assert distance.tolist() == pytest.approx([0.298412466], rel=1e-6)


def test_persistent_dwells_produce_reverse_jump():
    sequence = np.array(
        [[0], [0], [0], [-1], [0], [0], [1], [1], [1], [1], [0], [0], [0]]
    )
    dwells, events = extract_dwells_and_jumps(
        sequence,
        frame_spacing_ps=0.1,
        min_dwell_frames=3,
        max_unassigned_gap_frames=1,
        max_transition_gap_frames=3,
    )
    assert [dwell["site"] for dwell in dwells] == [0, 1, 0]
    assert [(event.origin_site, event.destination_site) for event in events] == [
        (0, 1),
        (1, 0),
    ]
    reverse = reverse_jump_statistics(
        events, reverse_window_ps=2.0, observation_end_ps=3.0
    )
    assert reverse["reverse_pairs"] == 1
    assert reverse["eligible_origin_jumps"] == 2
    assert reverse["reverse_pair_fraction"] == pytest.approx(0.5)


def test_reverse_denominator_includes_observed_nonreturning_jumps():
    events = [
        JumpEvent(0, 0, 1, 1.0, 0.0),
        JumpEvent(0, 1, 2, 4.0, 0.0),
    ]
    reverse = reverse_jump_statistics(
        events, reverse_window_ps=2.0, observation_end_ps=5.0
    )
    assert reverse["eligible_origin_jumps"] == 1
    assert reverse["next_jumps_within_window"] == 0
    assert reverse["reverse_pair_fraction"] == pytest.approx(0.0)


def test_string_graph_and_null_are_deterministic():
    events = [
        JumpEvent(0, 0, 1, 1.0, 0.0),
        JumpEvent(1, 1, 2, 1.1, 0.0),
        JumpEvent(2, 3, 4, 4.0, 0.0),
    ]
    observed = string_statistics(events, time_window_ps=0.2)
    assert observed["connected_event_fraction"] == pytest.approx(2 / 3)
    assert observed["unique_ion_string_sizes"] == [2]
    first = null_corrected_string_statistics(
        events,
        duration_ps=5.0,
        time_window_ps=0.2,
        replicates=20,
        seed=9,
    )
    second = null_corrected_string_statistics(
        events,
        duration_ps=5.0,
        time_window_ps=0.2,
        replicates=20,
        seed=9,
    )
    assert first == second


def test_circular_string_graph_connects_events_across_time_boundary():
    events = [
        JumpEvent(0, 0, 1, 0.05, 0.0),
        JumpEvent(1, 1, 2, 4.95, 0.0),
    ]
    linear = string_statistics(events, time_window_ps=0.2)
    circular = string_statistics(
        events, time_window_ps=0.2, circular_duration_ps=5.0
    )
    assert linear["connected_event_fraction"] == pytest.approx(0.0)
    assert circular["connected_event_fraction"] == pytest.approx(1.0)
