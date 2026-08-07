"""Preregistered robustness grid for LLZTO site and jump mechanisms."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .mechanisms import (
    JumpEvent,
    analyze_trajectory,
    build_llzto_site_model,
    reverse_jump_statistics,
)
from .provenance import atomic_write_json, sha256_file


def summarize_sensitivity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize whether mechanism conclusions survive all quality-passing rows."""
    accepted = [row for row in rows if row["quality_gate_pass"]]
    if not accepted:
        return {
            "n_settings": len(rows),
            "n_quality_passing_settings": 0,
            "all_settings_pass_quality": False,
            "mechanism_robustness_gate_pass": False,
            "failure": "no sensitivity setting passed the assignment quality gate",
        }
    excess = np.asarray(
        [row["primary_string"]["observed_minus_null_mean"] for row in accepted]
    )
    p_values = np.asarray(
        [row["primary_string"]["empirical_upper_tail_p"] for row in accepted]
    )
    reverse_values = [
        value
        for row in accepted
        for value in row["reverse_pair_fraction_by_window_ps"].values()
        if value is not None
    ]
    excess_sign_stable = bool(np.all(excess > 0) or np.all(excess < 0))
    significance_flags = p_values <= 0.05
    significance_stable = bool(
        np.all(significance_flags) or not np.any(significance_flags)
    )
    all_quality = len(accepted) == len(rows)
    return {
        "n_settings": len(rows),
        "n_quality_passing_settings": len(accepted),
        "all_settings_pass_quality": all_quality,
        "primary_string_excess_range": [float(np.min(excess)), float(np.max(excess))],
        "primary_string_empirical_p_range": [
            float(np.min(p_values)),
            float(np.max(p_values)),
        ],
        "primary_string_excess_sign_stable": excess_sign_stable,
        "primary_string_significance_at_0.05_stable": significance_stable,
        "reverse_pair_fraction_range": (
            [float(min(reverse_values)), float(max(reverse_values))]
            if reverse_values
            else None
        ),
        "mechanism_robustness_gate_pass": (
            all_quality and excess_sign_stable and significance_stable
        ),
        "claim_rule": (
            "A cooperative-string significance claim additionally requires every "
            "quality-passing setting to have positive excess and empirical p<=0.05."
        ),
        "cooperative_string_claim_supported_across_grid": bool(
            all_quality and np.all(excess > 0) and np.all(significance_flags)
        ),
    }


def run_sensitivity_grid(
    trajectory_path: Path | str,
    protocol_path: Path | str,
    *,
    cif_path: Path | str,
) -> dict[str, Any]:
    """Run the frozen cutoff/dwell grid and reverse-window sensitivity."""
    trajectory = Path(trajectory_path).resolve()
    protocol_source = Path(protocol_path).resolve()
    protocol = json.loads(protocol_source.read_text(encoding="utf-8"))
    if protocol.get("schema_version") != "1.0":
        raise ValueError("unsupported mechanism protocol schema")
    frozen_trajectories = protocol.get("trajectories")
    if frozen_trajectories is not None:
        expected_trajectory_hash = frozen_trajectories.get(trajectory.stem)
        if expected_trajectory_hash is None:
            raise RuntimeError(
                f"trajectory {trajectory.stem!r} is not frozen in the pilot protocol"
            )
        if sha256_file(trajectory) != expected_trajectory_hash:
            raise RuntimeError("pilot trajectory hash does not match the frozen protocol")
    site_settings = protocol["site_model"]
    if sha256_file(cif_path) != site_settings["source_sha256"]:
        raise RuntimeError("mechanism CIF hash does not match the frozen protocol")
    primary = protocol["analysis"]
    sensitivity = protocol["sensitivity"]
    quality = protocol["quality_gate"]
    site_model = build_llzto_site_model(
        cif_path,
        split_site_cutoff_angstrom=site_settings["split_site_cutoff_angstrom"],
        oxygen_coordination_cutoff_angstrom=site_settings[
            "oxygen_coordination_cutoff_angstrom"
        ],
    )
    primary_string_window = float(primary["primary_string_window_ps"])
    rows = []
    for assignment_cutoff in sensitivity["assignment_cutoff_angstrom"]:
        for min_dwell in sensitivity["min_dwell_ps"]:
            result = analyze_trajectory(
                trajectory,
                site_model,
                frame_spacing_ps=primary["frame_spacing_ps"],
                assignment_cutoff_angstrom=assignment_cutoff,
                min_dwell_ps=min_dwell,
                max_unassigned_gap_ps=primary["max_unassigned_gap_ps"],
                max_transition_gap_ps=primary["max_transition_gap_ps"],
                reverse_window_ps=primary["reverse_window_ps"],
                string_windows_ps=[primary_string_window],
                null_replicates=primary["null_replicates"],
                null_seed=primary["null_seed"],
                min_assignment_fraction=quality["min_assignment_fraction"],
                max_collision_frame_fraction=quality["max_collision_frame_fraction"],
            )
            events = [JumpEvent(**row) for row in result["jump_events"]]
            reverse = {
                f"{window:g}": reverse_jump_statistics(
                    events,
                    reverse_window_ps=float(window),
                    observation_end_ps=result["trajectory_summary"]["duration_ps"],
                )["reverse_pair_fraction"]
                for window in sensitivity["reverse_window_ps"]
            }
            string = result["strings"][f"{primary_string_window:g}"]
            rows.append(
                {
                    "assignment_cutoff_angstrom": assignment_cutoff,
                    "min_dwell_ps": min_dwell,
                    "quality_gate_pass": result["quality_gate_pass"],
                    "assignment_fraction": result["trajectory_summary"][
                        "assignment_fraction"
                    ],
                    "collision_frame_fraction": result["trajectory_summary"][
                        "collision_frame_fraction"
                    ],
                    "n_jumps": result["n_jumps"],
                    "jump_rate_per_ion_ps": result["jump_rate_per_ion_ps"],
                    "reverse_pair_fraction_by_window_ps": reverse,
                    "primary_string": {
                        "time_window_ps": primary_string_window,
                        "observed_connected_event_fraction": string["observed"][
                            "connected_event_fraction"
                        ],
                        "null_connected_event_fraction_mean": string[
                            "null_connected_event_fraction_mean"
                        ],
                        "observed_minus_null_mean": string["observed_minus_null_mean"],
                        "empirical_upper_tail_p": string["empirical_upper_tail_p"],
                    },
                    "mean_mobile_population_by_site_type": result[
                        "mean_mobile_population_by_site_type"
                    ],
                    "dwell_summary_by_site_type": result["dwell_summary_by_site_type"],
                }
            )
    return {
        "schema_version": "1.0",
        "analysis_kind": "llzto-mechanism-sensitivity",
        "trajectory_path": str(trajectory),
        "trajectory_sha256": sha256_file(trajectory),
        "protocol_path": str(protocol_source),
        "protocol_sha256": sha256_file(protocol_source),
        "site_model_fingerprint": site_model["site_model_fingerprint"],
        "rows": rows,
        "summary": summarize_sensitivity(rows),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory")
    parser.add_argument("protocol")
    parser.add_argument("--cif", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_sensitivity_grid(args.trajectory, args.protocol, cif_path=args.cif)
    report["implementation_path"] = str(Path(__file__).resolve())
    report["implementation_sha256"] = sha256_file(Path(__file__))
    output = Path(args.out).resolve()
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing != report:
            raise RuntimeError(
                f"refusing to overwrite mechanism-sensitivity report: {output}"
            )
        print(json.dumps(report, indent=2))
        return
    atomic_write_json(output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
