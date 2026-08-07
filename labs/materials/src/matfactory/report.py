"""Build campaign-level convergence reports and diagnostic figures."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, sha256_file


def load_campaign_results(root: Path | str) -> dict[str, dict[str, Any]]:
    campaign_root = Path(root)
    results: dict[str, dict[str, Any]] = {}
    for path in sorted(campaign_root.glob("*/result.json")):
        results[path.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    return results


def _diagnostics(run_dir: Path, temperature: int) -> dict[str, Any]:
    path = run_dir / f"T{temperature}.transport.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get(
        "trajectory_diagnostics", {}
    )


def mean_sd_ci95(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "sample_sd": None, "ci95": None}
    mean = statistics.fmean(values)
    if len(values) == 1:
        return {"n": 1, "mean": mean, "sample_sd": None, "ci95": None}
    sd = statistics.stdev(values)
    try:
        from scipy.stats import t

        critical = float(t.ppf(0.975, len(values) - 1))
    except ImportError:
        critical = 1.96
    return {
        "n": len(values),
        "mean": mean,
        "sample_sd": sd,
        "ci95": critical * sd / math.sqrt(len(values)),
    }


def _numerical_summary(
    root: Path, results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for run_id, result in results.items():
        config = result.get("config", {})
        if config.get("protocol_tier") != "numerics":
            continue
        for point in result.get("points", []):
            diagnostics = _diagnostics(root / run_id, int(point["temperature"]))
            steps = int(config["equilibration_steps"]) + int(
                config["production_steps"]
            )
            drift = diagnostics.get("total_energy_drift_mev_atom_ps")
            limit = float(config["max_abs_nve_energy_drift_mev_atom_ps"])
            rows.append(
                {
                    "run_id": run_id,
                    "timestep_fs": float(config["timestep_fs"]),
                    "temperature_k": int(point["temperature"]),
                    "temperature_mean_k": diagnostics.get("temperature_mean_k"),
                    "temperature_std_k": diagnostics.get("temperature_std_k"),
                    "energy_drift_mev_atom_ps": drift,
                    "energy_drift_limit_mev_atom_ps": limit,
                    "energy_drift_pass": bool(
                        drift is not None and abs(float(drift)) <= limit
                    ),
                    "minimum_distance_angstrom": diagnostics.get(
                        "minimum_distance_angstrom"
                    ),
                    "steps_per_second": steps / float(point["wall_seconds"]),
                    "tracer_diffusivity_cm2_s": point["diffusivity_cm2_s"],
                    "tracer_alpha": point.get("diffusive_exponent"),
                    "tracer_resolved": point.get("resolved", False),
                    "tracer_rejection_reasons": point.get(
                        "rejection_reasons", []
                    ),
                }
            )
    passing = [row for row in rows if row["energy_drift_pass"]]
    selected = max(passing, key=lambda row: row["timestep_fs"], default=None)
    return {
        "runs": rows,
        "all_energy_drift_checks_pass": bool(rows) and len(passing) == len(rows),
        "selected_timestep_fs": (
            selected["timestep_fs"] if selected is not None else None
        ),
        "selection_rule": (
            "largest tested timestep passing the preregistered NVE energy-drift "
            "limit; short-run diffusion values are not used for selection"
        ),
    }


def _transport_rows(
    root: Path, results: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_id, result in results.items():
        config = result.get("config", {})
        for point in result.get("points", []):
            diagnostics = _diagnostics(root / run_id, int(point["temperature"]))
            rows.append(
                {
                    "run_id": run_id,
                    "protocol_tier": config.get("protocol_tier"),
                    "occupancy_seed": config.get("occupancy_seed"),
                    "velocity_seed_base": config.get("seed"),
                    "primitive_cell": config.get("primitive_cell"),
                    "temperature_k": point["temperature"],
                    "production_ps": point["production_ps"],
                    "temperature_mean_k": point.get("temperature_mean_k"),
                    "temperature_std_k": point.get("temperature_std_k"),
                    "minimum_distance_angstrom": diagnostics.get(
                        "minimum_distance_angstrom"
                    ),
                    "tracer_diffusivity_cm2_s": point["diffusivity_cm2_s"],
                    "tracer_stderr_cm2_s": point.get(
                        "diffusivity_stderr_cm2_s"
                    ),
                    "tracer_alpha": point.get("diffusive_exponent"),
                    "tracer_msd_at_max_lag_a2": point.get(
                        "final_tracer_msd_a2"
                    ),
                    "tracer_resolved": point.get("resolved", False),
                    "tracer_rejection_reasons": point.get(
                        "rejection_reasons", []
                    ),
                    "collective_diffusivity_cm2_s": point.get(
                        "collective_diffusivity_cm2_s"
                    ),
                    "collective_stderr_cm2_s": point.get(
                        "collective_diffusivity_stderr_cm2_s"
                    ),
                    "collective_alpha": (
                        json.loads(
                            (
                                root
                                / run_id
                                / f"T{point['temperature']}.transport.json"
                            ).read_text(encoding="utf-8")
                        )
                        .get("transport", {})
                        .get("collective", {})
                        .get("diffusive_exponent")
                    ),
                    "collective_msd_at_max_lag_a2": point.get(
                        "final_collective_msd_a2"
                    ),
                    "collective_resolved": point.get(
                        "collective_resolved", False
                    ),
                    "collective_rejection_reasons": point.get(
                        "collective_rejection_reasons", []
                    ),
                    "collective_to_tracer_ratio": point.get(
                        "collective_to_tracer_ratio"
                    ),
                    "protocol_fingerprint": point.get("protocol_fingerprint"),
                }
            )
    return rows


def _replicate_summary(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    formal = [
        result
        for result in results.values()
        if result.get("config", {}).get("protocol_tier") == "formal"
    ]
    tracer_energies = [
        float(result["arrhenius"]["activation_energy_ev"])
        for result in formal
        if "arrhenius" in result
    ]
    collective_energies = [
        float(result["arrhenius_collective"]["activation_energy_ev"])
        for result in formal
        if "arrhenius_collective" in result
    ]
    return {
        "n_formal_runs_found": len(formal),
        "n_resolved_tracer_arrhenius_runs": len(tracer_energies),
        "n_resolved_collective_arrhenius_runs": len(collective_energies),
        "tracer_activation_energy_ev": mean_sd_ci95(tracer_energies),
        "collective_activation_energy_ev": mean_sd_ci95(collective_energies),
        "aggregation_rule": (
            "fit each occupancy realization independently, then summarize the "
            "replicate estimates; temperature points are not pooled as independent"
        ),
    }


def build_campaign_report(root: Path | str) -> dict[str, Any]:
    campaign_root = Path(root).resolve()
    results = load_campaign_results(campaign_root)
    state_path = campaign_root / "campaign_state.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else None
    )
    transport = _transport_rows(campaign_root, results)
    formal_summary = _replicate_summary(results)
    return {
        "schema_version": "1.0",
        "campaign_root": str(campaign_root),
        "campaign_state_sha256": (
            sha256_file(state_path) if state_path.exists() else None
        ),
        "campaign_id": state.get("campaign_id") if state else None,
        "protocol_sha256": state.get("protocol_sha256") if state else None,
        "n_completed_result_files": len(results),
        "numerical_gate": _numerical_summary(campaign_root, results),
        "transport_points": transport,
        "formal_replicate_summary": formal_summary,
        "counts": {
            "transport_points": len(transport),
            "tracer_resolved": sum(row["tracer_resolved"] for row in transport),
            "collective_resolved": sum(
                row["collective_resolved"] for row in transport
            ),
        },
        "publication_claims_ready": False,
        "publication_blockers": [
            "independent DFT snapshot validation is not present",
            "formal 0.5 ns configuration replicas are not all resolved",
            "finite-size, velocity, and volume sensitivity runs are incomplete",
        ],
    }


def plot_campaign_diagnostics(
    root: Path | str, out_prefix: Path | str
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    campaign_root = Path(root).resolve()
    results = load_campaign_results(campaign_root)
    report = build_campaign_report(campaign_root)
    figure, axes = plt.subplots(1, 3, figsize=(14.0, 4.2))

    numerical = report["numerical_gate"]["runs"]
    if numerical:
        labels = [f"{row['timestep_fs']:g} fs" for row in numerical]
        drifts = [abs(row["energy_drift_mev_atom_ps"]) for row in numerical]
        axes[0].bar(labels, drifts, color="#4C72B0")
        axes[0].axhline(
            numerical[0]["energy_drift_limit_mev_atom_ps"],
            color="#C44E52",
            linestyle="--",
            label="preregistered limit",
        )
        axes[0].legend(frameon=False, fontsize=8)
    axes[0].set_ylabel("|energy drift| (meV atom$^{-1}$ ps$^{-1}$)")
    axes[0].set_title("Integration stability")

    colours = plt.cm.viridis(np.linspace(0.1, 0.9, max(1, len(results))))
    for colour, (run_id, result) in zip(colours, sorted(results.items())):
        for point in result.get("points", []):
            path = campaign_root / run_id / f"T{point['temperature']}.transport.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            curve = payload["transport"]["curve"]
            label = f"{run_id}: {point['temperature']} K"
            axes[1].loglog(
                curve["times_ps"], curve["tracer_msd_a2"], color=colour, label=label
            )
            marker = "o" if point.get("resolved") else "o"
            face = colour if point.get("resolved") else "none"
            axes[2].errorbar(
                1000.0 / float(point["temperature"]),
                point["diffusivity_cm2_s"],
                yerr=point.get("diffusivity_stderr_cm2_s"),
                marker=marker,
                markerfacecolor=face,
                markeredgecolor=colour,
                color=colour,
                linestyle="none",
                capsize=2,
                label=label,
            )
    axes[1].set_xlabel("lag time (ps)")
    axes[1].set_ylabel("tracer MSD (Å$^2$)")
    axes[1].set_title("MSD convergence")
    if results:
        axes[1].legend(frameon=False, fontsize=5)
    axes[2].set_yscale("log")
    axes[2].set_xlabel("1000/T (K$^{-1}$)")
    axes[2].set_ylabel("tracer D (cm$^2$ s$^{-1}$)")
    axes[2].set_title("Filled = resolved")

    figure.tight_layout()
    prefix = Path(out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    outputs = [prefix.with_suffix(suffix) for suffix in (".svg", ".pdf", ".png")]
    for path in outputs:
        figure.savefig(path, dpi=300 if path.suffix == ".png" else None)
    plt.close(figure)
    return outputs


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--figure-prefix", default=None)
    args = parser.parse_args()

    root = Path(args.campaign_root)
    out = Path(args.out) if args.out else root / "analysis/campaign_report.json"
    report = build_campaign_report(root)
    atomic_write_json(out, report)
    print(f"wrote {out}")
    prefix = (
        Path(args.figure_prefix)
        if args.figure_prefix
        else root / "analysis/campaign_diagnostics"
    )
    for path in plot_campaign_diagnostics(root, prefix):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
