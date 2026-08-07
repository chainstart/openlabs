"""Compare literature-extracted activation energies against MLIP predictions.

This is the deliverable the whole pipeline exists to produce: an experimental Ea
distribution taken from papers, and an Ea computed from molecular dynamics on the
same composition, plotted against each other.

Two things keep the comparison honest:

* The experimental values come from tables in papers, never from the Materials
  Project. MP is in CHGNet's training set, so an MP-derived label would leak and
  the agreement would be circular.
* The MLIP Ea is extrapolated from high-temperature MD, and the fitted
  temperature range travels with every point. Extrapolating a high-temperature
  Arrhenius slope down to room temperature is the dominant systematic error, and
  hiding it would make the comparison look better than it is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SIGMA_KEYS = ("total_conductivity", "ionic_conductivity", "bulk_conductivity")


@dataclass
class ExperimentalPoint:
    """One measured activation energy, with the provenance to re-check it."""

    activation_energy_ev: float
    conductivity_s_cm: float | None
    relative_density: float | None
    sample: str
    doi: str | None
    doc_id: str | None
    year: int | None
    table_index: int | None
    table_offset: int | None
    material_class: str | None
    chemistry: str | None
    activation_energy_sources: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def load_experimental(
    path: Path | str,
    *,
    material_class: str | None = "ceramic",
    chemistry: str | None = "garnet",
    require_conductivity: bool = False,
    allow_unlabelled: bool = False,
) -> list[ExperimentalPoint]:
    """Read activation energies out of a harvested fact file.

    Defaults to ceramic garnets, and both filters are load-bearing. Polymer
    electrolytes conduct by a different mechanism; NASICON-Na conducts a
    different ion entirely (NZSP sits near 0.14 eV against garnet's 0.3 eV).
    Either one silently pulls the experimental mean away from the material the
    MD actually simulated.

    Records predating the chemistry label are excluded by default. Keeping an
    unclassified legacy row in a garnet analysis is less reproducible than
    requiring a deterministic re-extraction; ``allow_unlabelled`` is available
    only for backwards-compatible inspection.
    """
    points: list[ExperimentalPoint] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if (record.get("property_conflicts") or {}).get("activation_energy"):
            continue
        properties = record.get("properties") or {}
        energy = properties.get("activation_energy")
        if not energy or energy.get("value") is None:
            continue
        if material_class and record.get("material_class") != material_class:
            continue
        family = record.get("chemistry")
        if chemistry:
            if family is None and not allow_unlabelled:
                continue
            if family is not None and family != chemistry:
                continue

        sigma = None
        for key in SIGMA_KEYS:
            if key in properties and properties[key].get("value") is not None:
                sigma = properties[key]["value"]
                break
        if require_conductivity and sigma is None:
            continue

        density = (properties.get("relative_density") or {}).get("value")
        points.append(
            ExperimentalPoint(
                activation_energy_ev=float(energy["value"]),
                conductivity_s_cm=sigma,
                relative_density=density,
                sample=record.get("sample") or "",
                doi=record.get("doi"),
                doc_id=record.get("doc_id"),
                year=record.get("year"),
                table_index=record.get("table_index"),
                table_offset=record.get("table_offset"),
                material_class=record.get("material_class"),
                chemistry=family,
                activation_energy_sources=energy.get("sources") or [],
            )
        )
    return points


def load_mlip(run_dir: Path | str) -> dict[str, Any] | None:
    """Read one MD run's Arrhenius result, if it finished."""
    path = Path(run_dir) / "result.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "arrhenius" not in payload:
        return None
    return payload


def summarise(values: list[float]) -> dict[str, float]:
    """Mean, standard deviation and quartiles, computed without numpy."""
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    mean = sum(ordered) / n
    variance = sum((v - mean) ** 2 for v in ordered) / (n - 1) if n > 1 else 0.0
    return {
        "n": n,
        "mean": mean,
        "std": variance ** 0.5,
        "min": ordered[0],
        "q1": ordered[n // 4],
        "median": ordered[n // 2],
        "q3": ordered[(3 * n) // 4],
        "max": ordered[-1],
    }


def plot_comparison(
    experimental: list[ExperimentalPoint],
    mlip_runs: dict[str, dict[str, Any]],
    *,
    out_path: Path | str = "figures/ea_experiment_vs_mlip.png",
    title: str = "Li-ion activation energy: literature vs CHGNet MD",
) -> Path:
    """Experimental Ea distribution with each MLIP prediction overlaid.

    A scatter of experiment against prediction is not possible yet: the
    literature samples are doped cubic compositions measured near room
    temperature, and each MD run is one composition. So the experimental spread
    is drawn as a distribution and each MLIP result as a vertical line with its
    fit uncertainty, which is the honest way to show a one-to-many comparison.
    """
    import matplotlib

    matplotlib.use("Agg")  # no display in WSL
    import matplotlib.pyplot as plt

    energies = [p.activation_energy_ev for p in experimental]
    if not energies:
        raise ValueError("no experimental activation energies to plot")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    figure, (left, right) = plt.subplots(
        1, 2, figsize=(11, 4.5), gridspec_kw={"width_ratios": [1.15, 1]}
    )

    left.hist(energies, bins=12, color="#4C72B0", alpha=0.75,
              edgecolor="white", label=f"literature (n={len(energies)})")
    colours = ["#C44E52", "#55A868", "#8172B2", "#CCB974"]
    for index, (label, payload) in enumerate(sorted(mlip_runs.items())):
        fit = payload["arrhenius"]
        colour = colours[index % len(colours)]
        left.axvline(fit["activation_energy_ev"], color=colour, linewidth=2,
                     label=f"{label}: {fit['activation_energy_ev']:.3f} eV")
        stderr = fit.get("activation_energy_stderr_ev") or 0.0
        if stderr:
            left.axvspan(
                fit["activation_energy_ev"] - stderr,
                fit["activation_energy_ev"] + stderr,
                color=colour, alpha=0.18,
            )
    left.set_xlabel("activation energy (eV)")
    left.set_ylabel("number of literature samples")
    left.set_title("Distribution")
    left.legend(fontsize=8)

    # Arrhenius plot of the underlying MD, so the fit can be judged directly.
    for index, (label, payload) in enumerate(sorted(mlip_runs.items())):
        colour = colours[index % len(colours)]
        points = [p for p in payload["points"] if p["diffusivity_cm2_s"] > 0]
        inverse_t = [1000.0 / p["temperature"] for p in points]
        import math

        log_d = [math.log10(p["diffusivity_cm2_s"]) for p in points]
        right.plot(inverse_t, log_d, "o-", color=colour, label=label, markersize=5)
    right.set_xlabel("1000/T (1/K)")
    right.set_ylabel("log$_{10}$ D (cm$^2$/s)")
    right.set_title("MLIP Arrhenius fits")
    right.legend(fontsize=8)

    figure.suptitle(title, fontsize=11)
    figure.tight_layout()
    figure.savefig(out, dpi=160)
    plt.close(figure)
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", default="facts/llzo_v9.jsonl")
    parser.add_argument("--run-dir", action="append", default=None,
                        help="an MD run directory (repeatable)")
    parser.add_argument("--out", default="figures/ea_experiment_vs_mlip.png")
    parser.add_argument("--material-class", default="ceramic")
    parser.add_argument("--chemistry", default="garnet",
                        help="structural family to keep; '' keeps all")
    parser.add_argument("--report", default="logs/comparison.json")
    args = parser.parse_args()

    experimental = load_experimental(
        args.facts,
        material_class=args.material_class or None,
        chemistry=args.chemistry or None,
    )
    stats = summarise([p.activation_energy_ev for p in experimental])
    print(f"experimental Ea: n={stats.get('n')} "
          f"mean={stats.get('mean', 0):.3f} sd={stats.get('std', 0):.3f} "
          f"median={stats.get('median', 0):.3f} "
          f"range={stats.get('min', 0):.2f}-{stats.get('max', 0):.2f} eV")
    print(f"  from {len({p.doi for p in experimental if p.doi})} distinct DOIs")
    unlabelled = sum(1 for p in experimental if p.chemistry is None)
    if unlabelled:
        print(f"  warning: {unlabelled} record(s) predate the chemistry label "
              f"and were kept unfiltered; re-extract to classify them")

    runs: dict[str, dict[str, Any]] = {}
    for directory in args.run_dir or []:
        payload = load_mlip(directory)
        if payload is None:
            print(f"  {directory}: no finished Arrhenius fit yet")
            continue
        label = Path(directory).name
        runs[label] = payload
        fit = payload["arrhenius"]
        print(f"  {label}: Ea={fit['activation_energy_ev']:.3f} "
              f"+/-{fit['activation_energy_stderr_ev']:.3f} eV "
              f"(r2={fit['r2']:.3f}, {fit['n_points']} points, "
              f"{fit['temperature_range_k'][0]}-{fit['temperature_range_k'][1]} K)")

    report = {
        "experimental": stats,
        "experimental_dois": sorted({p.doi for p in experimental if p.doi}),
        "mlip": {
            label: payload["arrhenius"] for label, payload in runs.items()
        },
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if runs:
        path = plot_comparison(experimental, runs, out_path=args.out)
        print(f"wrote {path}")
    else:
        print("no MLIP runs finished; skipping the figure")


if __name__ == "__main__":
    main()
