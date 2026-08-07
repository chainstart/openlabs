"""Crystallographic-site and null-corrected Li jump analysis for LLZTO."""

from __future__ import annotations

import ast
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .provenance import atomic_write_json, fingerprint, sha256_file
from .structures import load_cif_preserving_disorder, structure_fingerprint


@dataclass(frozen=True)
class JumpEvent:
    """One persistent site-to-site transition by a labelled Li ion."""

    ion_index: int
    origin_site: int
    destination_site: int
    time_ps: float
    transition_gap_ps: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _minimum_image(delta_fractional: np.ndarray, cell: np.ndarray) -> np.ndarray:
    """Return exact minimum-image fractional vectors for a general periodic cell."""
    from ase.geometry import find_mic

    delta = np.asarray(delta_fractional, dtype=float)
    lattice = np.asarray(cell, dtype=float)
    if delta.shape[-1] != 3 or lattice.shape != (3, 3):
        raise ValueError("minimum-image inputs require (..., 3) vectors and a 3 x 3 cell")
    if abs(float(np.linalg.det(lattice))) < 1e-12:
        raise ValueError("minimum-image cell is singular")
    original_shape = delta.shape
    cartesian = delta.reshape(-1, 3) @ lattice
    mic_cartesian, _lengths = find_mic(cartesian, lattice, pbc=True)
    mic_fractional = np.asarray(mic_cartesian) @ np.linalg.inv(lattice)
    return mic_fractional.reshape(original_shape)


def _periodic_center(fractional: np.ndarray, cell: np.ndarray) -> np.ndarray:
    anchor = fractional[0]
    unwrapped = anchor + _minimum_image(fractional - anchor, cell)
    return np.mod(np.mean(unwrapped, axis=0), 1.0)


def _canonicalize_parser_warning(value: str) -> str:
    """Normalize mapping literals whose repr order depends on the hash seed."""
    lines = []
    for line in str(value).splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        for prefix in ("CIF=", "PMG=", "ratios="):
            if not stripped.startswith(prefix):
                continue
            try:
                parsed = ast.literal_eval(stripped[len(prefix) :])
            except (SyntaxError, ValueError):
                break
            if isinstance(parsed, dict):
                line = indent + prefix + json.dumps(
                    parsed, sort_keys=True, separators=(",", ":")
                )
            break
        lines.append(line)
    return "\n".join(lines)


def build_llzto_site_model(
    cif_path: Path | str,
    *,
    split_site_cutoff_angstrom: float = 1.2,
    oxygen_coordination_cutoff_angstrom: float = 3.0,
) -> dict[str, Any]:
    """Collapse diffraction split Li positions into physical Li basins."""
    if split_site_cutoff_angstrom <= 0:
        raise ValueError("split_site_cutoff_angstrom must be positive")
    source = Path(cif_path).resolve()
    structure, parser_warnings = load_cif_preserving_disorder(source, primitive=True)
    parser_warnings = sorted(
        _canonicalize_parser_warning(warning) for warning in parser_warnings
    )
    candidates: list[dict[str, Any]] = []
    oxygen_fractional = []
    for structure_index, site in enumerate(structure):
        elements = {element.symbol for element in site.species}
        if elements == {"Li"}:
            candidates.append(
                {
                    "structure_index": structure_index,
                    "occupancy": float(site.species.get("Li")),
                    "fractional": np.asarray(site.frac_coords, dtype=float),
                }
            )
        elif site.is_ordered and site.specie.symbol == "O":
            oxygen_fractional.append(np.asarray(site.frac_coords, dtype=float))
    if not candidates:
        raise ValueError(f"no disordered Li candidates found in {source}")

    cell = np.asarray(structure.lattice.matrix, dtype=float)
    parent = list(range(len(candidates)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    for first in range(len(candidates)):
        for second in range(first + 1, len(candidates)):
            if not math.isclose(
                candidates[first]["occupancy"],
                candidates[second]["occupancy"],
                abs_tol=1e-8,
            ):
                continue
            delta = _minimum_image(
                candidates[first]["fractional"] - candidates[second]["fractional"],
                cell,
            )
            distance = float(np.linalg.norm(delta @ cell))
            if distance < split_site_cutoff_angstrom:
                union(first, second)

    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(candidates)):
        components[find(index)].append(index)

    oxygen = np.asarray(oxygen_fractional, dtype=float)
    basin_records = []
    for component in components.values():
        fractional = np.asarray(
            [candidates[index]["fractional"] for index in component], dtype=float
        )
        occupancies = [candidates[index]["occupancy"] for index in component]
        center = _periodic_center(fractional, cell)
        oxygen_delta = _minimum_image(oxygen - center, cell)
        oxygen_distances = np.linalg.norm(oxygen_delta @ cell, axis=1)
        coordination = int(
            np.count_nonzero(oxygen_distances <= oxygen_coordination_cutoff_angstrom)
        )
        if len(component) == 1 and occupancies[0] > 0.5:
            site_type = "tetrahedral-24d"
        elif len(component) == 2 and all(value < 0.5 for value in occupancies):
            site_type = "octahedral-96h-pair"
        else:
            site_type = "unclassified"
        basin_records.append(
            {
                "site_type": site_type,
                "fractional_center": center.tolist(),
                "candidate_structure_indices": sorted(
                    candidates[index]["structure_index"] for index in component
                ),
                "candidate_occupancies": occupancies,
                "summed_refined_occupancy": float(sum(occupancies)),
                "oxygen_coordination": coordination,
            }
        )

    basin_records.sort(
        key=lambda row: (
            row["site_type"],
            *(round(value, 12) for value in row["fractional_center"]),
        )
    )
    counters: Counter[str] = Counter()
    for basin_index, row in enumerate(basin_records):
        type_index = counters[row["site_type"]]
        counters[row["site_type"]] += 1
        prefix = "tet" if row["site_type"].startswith("tetrahedral") else "oct"
        row["basin_index"] = basin_index
        row["site_id"] = f"{prefix}-{type_index:02d}"

    model = {
        "schema_version": "1.0",
        "source_cif": str(source),
        "source_cif_sha256": sha256_file(source),
        "source_structure_fingerprint": structure_fingerprint(structure),
        "source_parser_warnings": parser_warnings,
        "primitive_lattice_angstrom": cell.tolist(),
        "split_site_cutoff_angstrom": split_site_cutoff_angstrom,
        "oxygen_coordination_cutoff_angstrom": (oxygen_coordination_cutoff_angstrom),
        "n_candidate_positions": len(candidates),
        "n_basins": len(basin_records),
        "site_type_counts": dict(sorted(counters.items())),
        "basins": basin_records,
    }
    model["site_model_fingerprint"] = fingerprint(model)
    return model


def assign_fractional_positions(
    fractional_positions: np.ndarray,
    cell: np.ndarray,
    basin_centers: np.ndarray,
    *,
    max_distance_angstrom: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Assign positions to nearest basins under a triclinic minimum image."""
    fractional = np.asarray(fractional_positions, dtype=float)
    lattice = np.asarray(cell, dtype=float)
    centers = np.asarray(basin_centers, dtype=float)
    if fractional.ndim != 2 or fractional.shape[1] != 3:
        raise ValueError("fractional_positions must be N x 3")
    if centers.ndim != 2 or centers.shape[1] != 3:
        raise ValueError("basin_centers must be M x 3")
    delta = _minimum_image(
        fractional[:, None, :] - centers[None, :, :], lattice
    )
    distances = np.linalg.norm(delta @ lattice, axis=2)
    nearest = np.argmin(distances, axis=1)
    nearest_distance = distances[np.arange(len(fractional)), nearest]
    assignments = nearest.astype(int)
    assignments[nearest_distance > max_distance_angstrom] = -1
    return assignments, nearest_distance


def assign_trajectory(
    frames: list[Any],
    site_model: dict[str, Any],
    *,
    max_distance_angstrom: float,
    mobile_species: str = "Li",
) -> dict[str, Any]:
    """Assign every mobile ion after removing host-framework translation."""
    if not frames:
        raise ValueError("cannot assign an empty trajectory")
    symbols = frames[0].get_chemical_symbols()
    mobile_indices = np.array(
        [index for index, symbol in enumerate(symbols) if symbol == mobile_species],
        dtype=int,
    )
    framework_indices = np.array(
        [index for index, symbol in enumerate(symbols) if symbol != mobile_species],
        dtype=int,
    )
    if not len(mobile_indices) or not len(framework_indices):
        raise ValueError("trajectory must contain mobile ions and a framework")
    centers = np.asarray(
        [row["fractional_center"] for row in site_model["basins"]], dtype=float
    )
    reference_cell = np.asarray(frames[0].cell.array, dtype=float)
    reference_fractional = np.asarray(
        frames[0].get_scaled_positions(wrap=True), dtype=float
    )
    assignments = []
    distances = []
    framework_drift = []
    collision_frames = 0
    for frame in frames:
        if frame.get_chemical_symbols() != symbols:
            raise ValueError("trajectory atom ordering changes between frames")
        cell = np.asarray(frame.cell.array, dtype=float)
        if not np.allclose(cell, reference_cell, atol=1e-7, rtol=1e-7):
            raise ValueError("site assignment requires a fixed-cell trajectory")
        fractional = np.asarray(frame.get_scaled_positions(wrap=True), dtype=float)
        framework_delta = _minimum_image(
            fractional[framework_indices] - reference_fractional[framework_indices],
            cell,
        )
        drift_cartesian = np.mean(framework_delta @ cell, axis=0)
        drift_fractional = np.linalg.solve(cell.T, drift_cartesian)
        corrected_mobile = np.mod(fractional[mobile_indices] - drift_fractional, 1.0)
        frame_assignments, frame_distances = assign_fractional_positions(
            corrected_mobile,
            cell,
            centers,
            max_distance_angstrom=max_distance_angstrom,
        )
        assigned = frame_assignments[frame_assignments >= 0]
        if len(assigned) != len(set(assigned.tolist())):
            collision_frames += 1
        assignments.append(frame_assignments)
        distances.append(frame_distances)
        framework_drift.append(float(np.linalg.norm(drift_cartesian)))
    return {
        "assignments": np.asarray(assignments, dtype=int),
        "nearest_distances_angstrom": np.asarray(distances, dtype=float),
        "mobile_atom_indices": mobile_indices,
        "framework_drift_angstrom": np.asarray(framework_drift, dtype=float),
        "collision_frames": collision_frames,
    }


def _runs(sequence: np.ndarray) -> list[tuple[int, int, int]]:
    if not len(sequence):
        return []
    output = []
    start = 0
    for index in range(1, len(sequence) + 1):
        if index == len(sequence) or sequence[index] != sequence[start]:
            output.append((int(sequence[start]), start, index - 1))
            start = index
    return output


def _bridge_short_unassigned(sequence: np.ndarray, max_gap_frames: int) -> np.ndarray:
    bridged = np.asarray(sequence, dtype=int).copy()
    if max_gap_frames <= 0:
        return bridged
    for value, start, end in _runs(bridged):
        if (
            value == -1
            and end - start + 1 <= max_gap_frames
            and start > 0
            and end + 1 < len(bridged)
            and bridged[start - 1] == bridged[end + 1]
            and bridged[start - 1] >= 0
        ):
            bridged[start : end + 1] = bridged[start - 1]
    return bridged


def extract_dwells_and_jumps(
    assignments: np.ndarray,
    *,
    frame_spacing_ps: float,
    min_dwell_frames: int,
    max_unassigned_gap_frames: int,
    max_transition_gap_frames: int,
) -> tuple[list[dict[str, Any]], list[JumpEvent]]:
    """Extract persistent dwells and jumps from frame-by-ion assignments."""
    values = np.asarray(assignments, dtype=int)
    if values.ndim != 2:
        raise ValueError("assignments must be frame x ion")
    if min_dwell_frames <= 0 or frame_spacing_ps <= 0:
        raise ValueError("frame spacing and minimum dwell must be positive")
    dwells: list[dict[str, Any]] = []
    jumps: list[JumpEvent] = []
    for ion_index in range(values.shape[1]):
        sequence = _bridge_short_unassigned(
            values[:, ion_index], max_unassigned_gap_frames
        )
        stable = [
            (site, start, end)
            for site, start, end in _runs(sequence)
            if site >= 0 and end - start + 1 >= min_dwell_frames
        ]
        merged: list[list[int]] = []
        for site, start, end in stable:
            intervening_frames = start - merged[-1][2] - 1 if merged else 0
            if (
                merged
                and merged[-1][0] == site
                and intervening_frames <= max_transition_gap_frames
            ):
                merged[-1][2] = end
            else:
                merged.append([site, start, end])
        for site, start, end in merged:
            dwells.append(
                {
                    "ion_index": ion_index,
                    "site": site,
                    "start_frame": start,
                    "end_frame": end,
                    "stable_duration_ps": (end - start + 1) * frame_spacing_ps,
                }
            )
        for previous, current in zip(merged, merged[1:]):
            origin, _origin_start, origin_end = previous
            destination, destination_start, _destination_end = current
            if origin == destination:
                continue
            gap_frames = destination_start - origin_end - 1
            if gap_frames > max_transition_gap_frames:
                continue
            jumps.append(
                JumpEvent(
                    ion_index=ion_index,
                    origin_site=origin,
                    destination_site=destination,
                    time_ps=(origin_end + destination_start) * 0.5 * frame_spacing_ps,
                    transition_gap_ps=max(gap_frames, 0) * frame_spacing_ps,
                )
            )
    jumps.sort(key=lambda event: (event.time_ps, event.ion_index))
    return dwells, jumps


def reverse_jump_statistics(
    events: list[JumpEvent],
    *,
    reverse_window_ps: float,
    observation_end_ps: float,
) -> dict[str, Any]:
    """Estimate the probability that an adequately observed jump is reversed.

    Every origin jump with a complete subsequent observation window enters the
    denominator. A jump with no following event inside the window is therefore
    a non-reversal instead of being silently removed from the denominator.
    """
    if reverse_window_ps <= 0 or observation_end_ps <= 0:
        raise ValueError("reverse window and observation end must be positive")
    if events and max(event.time_ps for event in events) > observation_end_ps:
        raise ValueError("a jump occurs after the observation end")
    by_ion: dict[int, list[JumpEvent]] = defaultdict(list)
    for event in events:
        by_ion[event.ion_index].append(event)
    eligible_origin_jumps = 0
    next_jumps_within_window = 0
    reverse_pairs = 0
    delays = []
    for ion_events in by_ion.values():
        ion_events.sort(key=lambda event: event.time_ps)
        for index, first in enumerate(ion_events):
            if first.time_ps + reverse_window_ps > observation_end_ps:
                continue
            eligible_origin_jumps += 1
            if index + 1 >= len(ion_events):
                continue
            second = ion_events[index + 1]
            delay = second.time_ps - first.time_ps
            if delay <= reverse_window_ps:
                next_jumps_within_window += 1
                if (
                    first.origin_site == second.destination_site
                    and first.destination_site == second.origin_site
                ):
                    reverse_pairs += 1
                    delays.append(delay)
    return {
        "reverse_window_ps": reverse_window_ps,
        "observation_end_ps": observation_end_ps,
        "eligible_origin_jumps": eligible_origin_jumps,
        "next_jumps_within_window": next_jumps_within_window,
        "reverse_pairs": reverse_pairs,
        "reverse_pair_fraction": (
            reverse_pairs / eligible_origin_jumps if eligible_origin_jumps else None
        ),
        "denominator_definition": (
            "all origin jumps whose complete reverse window lies inside the trajectory"
        ),
        "reverse_delay_mean_ps": float(np.mean(delays)) if delays else None,
    }


def string_statistics(
    events: list[JumpEvent],
    *,
    time_window_ps: float,
    circular_duration_ps: float | None = None,
) -> dict[str, Any]:
    """Connect causally compatible jumps within a temporal window."""
    if time_window_ps <= 0:
        raise ValueError("time_window_ps must be positive")
    if circular_duration_ps is not None:
        if circular_duration_ps <= 0 or time_window_ps > circular_duration_ps / 2:
            raise ValueError("invalid circular duration for the string window")
        if any(not 0 <= event.time_ps < circular_duration_ps for event in events):
            raise ValueError("circular event times must lie inside the duration")
    ordered = sorted(events, key=lambda event: event.time_ps)
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        a = find(first)
        b = find(second)
        if a != b:
            parent[b] = a

    for first, event in enumerate(ordered):
        for second in range(first + 1, len(ordered)):
            other = ordered[second]
            separation = other.time_ps - event.time_ps
            if circular_duration_ps is None:
                if separation > time_window_ps:
                    break
            else:
                separation = min(separation, circular_duration_ps - separation)
                if separation > time_window_ps:
                    continue
            if event.ion_index == other.ion_index:
                continue
            if (
                event.destination_site == other.origin_site
                or other.destination_site == event.origin_site
            ):
                union(first, second)

    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(ordered)):
        components[find(index)].append(index)
    string_sizes = []
    connected_events = 0
    for indices in components.values():
        unique_ions = {ordered[index].ion_index for index in indices}
        if len(unique_ions) >= 2:
            string_sizes.append(len(unique_ions))
            connected_events += len(indices)
    return {
        "time_window_ps": time_window_ps,
        "time_topology": "circular" if circular_duration_ps is not None else "linear",
        "circular_duration_ps": circular_duration_ps,
        "n_events": len(ordered),
        "n_multion_components": len(string_sizes),
        "connected_event_fraction": (
            connected_events / len(ordered) if ordered else None
        ),
        "unique_ion_string_sizes": sorted(string_sizes),
        "mean_unique_ion_string_size": (
            float(np.mean(string_sizes)) if string_sizes else None
        ),
        "max_unique_ion_string_size": max(string_sizes, default=0),
    }


def null_corrected_string_statistics(
    events: list[JumpEvent],
    *,
    duration_ps: float,
    time_window_ps: float,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    """Compare observed strings with independent per-ion circular time shifts."""
    if duration_ps <= 0 or replicates <= 0:
        raise ValueError("duration and null replicate count must be positive")
    observed = string_statistics(events, time_window_ps=time_window_ps)
    rng = np.random.default_rng(seed)
    ion_ids = sorted({event.ion_index for event in events})
    null_fractions = []
    for _replicate in range(replicates):
        shifts = {ion: float(rng.uniform(0.0, duration_ps)) for ion in ion_ids}
        shifted = [
            JumpEvent(
                ion_index=event.ion_index,
                origin_site=event.origin_site,
                destination_site=event.destination_site,
                time_ps=(event.time_ps + shifts[event.ion_index]) % duration_ps,
                transition_gap_ps=event.transition_gap_ps,
            )
            for event in events
        ]
        statistic = string_statistics(
            shifted,
            time_window_ps=time_window_ps,
            circular_duration_ps=duration_ps,
        )["connected_event_fraction"]
        null_fractions.append(float(statistic or 0.0))
    observed_fraction = float(observed["connected_event_fraction"] or 0.0)
    null_array = np.asarray(null_fractions, dtype=float)
    return {
        "observed": observed,
        "null_model": (
            "independent uniform circular time shift for each labelled ion, "
            "with circular boundary-aware event connectivity"
        ),
        "null_replicates": replicates,
        "null_seed": seed,
        "null_connected_event_fraction_mean": float(np.mean(null_array)),
        "null_connected_event_fraction_std": float(np.std(null_array, ddof=1)),
        "null_connected_event_fraction_p95": float(np.percentile(null_array, 95)),
        "observed_minus_null_mean": observed_fraction - float(np.mean(null_array)),
        "empirical_upper_tail_p": float(
            (1 + np.count_nonzero(null_array >= observed_fraction)) / (replicates + 1)
        ),
    }


def analyze_trajectory(
    trajectory_path: Path | str,
    site_model: dict[str, Any],
    *,
    frame_spacing_ps: float,
    assignment_cutoff_angstrom: float,
    min_dwell_ps: float,
    max_unassigned_gap_ps: float,
    max_transition_gap_ps: float,
    reverse_window_ps: float,
    string_windows_ps: list[float],
    null_replicates: int,
    null_seed: int,
    min_assignment_fraction: float,
    max_collision_frame_fraction: float,
) -> dict[str, Any]:
    """Run the full site, jump, reverse, and null-corrected string analysis."""
    from ase.io import read

    source = Path(trajectory_path).resolve()
    frames = list(read(source, index=":"))
    assigned = assign_trajectory(
        frames,
        site_model,
        max_distance_angstrom=assignment_cutoff_angstrom,
    )
    assignments = assigned["assignments"]
    distances = assigned["nearest_distances_angstrom"]
    min_dwell_frames = max(1, math.ceil(min_dwell_ps / frame_spacing_ps))
    max_gap_frames = max(0, math.floor(max_unassigned_gap_ps / frame_spacing_ps))
    max_transition_frames = max(0, math.floor(max_transition_gap_ps / frame_spacing_ps))
    dwells, events = extract_dwells_and_jumps(
        assignments,
        frame_spacing_ps=frame_spacing_ps,
        min_dwell_frames=min_dwell_frames,
        max_unassigned_gap_frames=max_gap_frames,
        max_transition_gap_frames=max_transition_frames,
    )
    n_frames, n_ions = assignments.shape
    valid = assignments >= 0
    assignment_fraction = float(np.mean(valid))
    collision_fraction = assigned["collision_frames"] / n_frames
    basin_counts = Counter(assignments[valid].tolist())
    types = [row["site_type"] for row in site_model["basins"]]
    type_population = Counter()
    for basin_index, count in basin_counts.items():
        type_population[types[basin_index]] += count
    transition_counts = Counter(
        f"{types[event.origin_site]} -> {types[event.destination_site]}"
        for event in events
    )
    dwell_by_type: dict[str, list[float]] = defaultdict(list)
    for dwell in dwells:
        dwell_by_type[types[dwell["site"]]].append(dwell["stable_duration_ps"])
    duration_ps = max((n_frames - 1) * frame_spacing_ps, frame_spacing_ps)
    string_results = {
        f"{window:g}": null_corrected_string_statistics(
            events,
            duration_ps=duration_ps,
            time_window_ps=window,
            replicates=null_replicates,
            seed=null_seed + index,
        )
        for index, window in enumerate(string_windows_ps)
    }
    quality_checks = {
        "assignment_fraction": assignment_fraction >= min_assignment_fraction,
        "collision_frame_fraction": (
            collision_fraction <= max_collision_frame_fraction
        ),
    }
    return {
        "schema_version": "1.0",
        "trajectory_path": str(source),
        "trajectory_sha256": sha256_file(source),
        "site_model_fingerprint": site_model["site_model_fingerprint"],
        "analysis_settings": {
            "frame_spacing_ps": frame_spacing_ps,
            "assignment_cutoff_angstrom": assignment_cutoff_angstrom,
            "min_dwell_ps": min_dwell_ps,
            "min_dwell_frames": min_dwell_frames,
            "max_unassigned_gap_ps": max_unassigned_gap_ps,
            "max_unassigned_gap_frames": max_gap_frames,
            "max_transition_gap_ps": max_transition_gap_ps,
            "max_transition_gap_frames": max_transition_frames,
            "reverse_window_ps": reverse_window_ps,
            "string_windows_ps": string_windows_ps,
            "null_replicates": null_replicates,
            "null_seed": null_seed,
        },
        "trajectory_summary": {
            "n_frames": n_frames,
            "n_mobile_ions": n_ions,
            "duration_ps": duration_ps,
            "assignment_fraction": assignment_fraction,
            "nearest_distance_p95_angstrom": float(np.percentile(distances, 95)),
            "nearest_distance_max_angstrom": float(np.max(distances)),
            "framework_drift_max_angstrom": float(
                np.max(assigned["framework_drift_angstrom"])
            ),
            "collision_frames": assigned["collision_frames"],
            "collision_frame_fraction": collision_fraction,
        },
        "quality_limits": {
            "min_assignment_fraction": min_assignment_fraction,
            "max_collision_frame_fraction": max_collision_frame_fraction,
        },
        "quality_checks": quality_checks,
        "quality_gate_pass": all(quality_checks.values()),
        "mean_site_occupancy": {
            site_model["basins"][index]["site_id"]: basin_counts.get(index, 0)
            / n_frames
            for index in range(len(types))
        },
        "mean_mobile_population_by_site_type": {
            site_type: count / n_frames
            for site_type, count in sorted(type_population.items())
        },
        "dwell_summary_by_site_type": {
            site_type: {
                "n_dwells": len(values),
                "mean_stable_duration_ps": float(np.mean(values)),
                "median_stable_duration_ps": float(np.median(values)),
            }
            for site_type, values in sorted(dwell_by_type.items())
        },
        "n_jumps": len(events),
        "jump_rate_per_ion_ps": len(events) / n_ions / duration_ps,
        "transition_counts": dict(sorted(transition_counts.items())),
        "reverse_jumps": reverse_jump_statistics(
            events,
            reverse_window_ps=reverse_window_ps,
            observation_end_ps=duration_ps,
        ),
        "strings": string_results,
        "dwells": dwells,
        "jump_events": [event.as_dict() for event in events],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory")
    parser.add_argument("protocol")
    parser.add_argument("--cif", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    protocol_path = Path(args.protocol).resolve()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("schema_version") != "1.0":
        raise ValueError("unsupported mechanism protocol schema")
    site = protocol["site_model"]
    if sha256_file(args.cif) != site["source_sha256"]:
        raise RuntimeError("mechanism CIF hash does not match the frozen protocol")
    analysis = protocol["analysis"]
    quality = protocol["quality_gate"]
    model = build_llzto_site_model(
        args.cif,
        split_site_cutoff_angstrom=site["split_site_cutoff_angstrom"],
        oxygen_coordination_cutoff_angstrom=site["oxygen_coordination_cutoff_angstrom"],
    )
    result = analyze_trajectory(
        args.trajectory,
        model,
        frame_spacing_ps=analysis["frame_spacing_ps"],
        assignment_cutoff_angstrom=analysis["assignment_cutoff_angstrom"],
        min_dwell_ps=analysis["min_dwell_ps"],
        max_unassigned_gap_ps=analysis["max_unassigned_gap_ps"],
        max_transition_gap_ps=analysis["max_transition_gap_ps"],
        reverse_window_ps=analysis["reverse_window_ps"],
        string_windows_ps=analysis["string_windows_ps"],
        null_replicates=analysis["null_replicates"],
        null_seed=analysis["null_seed"],
        min_assignment_fraction=quality["min_assignment_fraction"],
        max_collision_frame_fraction=quality["max_collision_frame_fraction"],
    )
    result["site_model"] = model
    result["protocol_path"] = str(protocol_path)
    result["protocol_sha256"] = sha256_file(protocol_path)
    result["implementation_path"] = str(Path(__file__).resolve())
    result["implementation_sha256"] = sha256_file(Path(__file__))
    output = Path(args.out).resolve()
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing != result:
            raise RuntimeError(f"refusing to overwrite mechanism report: {output}")
        print(json.dumps(result, indent=2))
        return
    atomic_write_json(output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
