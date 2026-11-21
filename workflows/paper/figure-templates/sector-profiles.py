"""Draw the profile intervals and paired product perturbations from verified tool JSON."""
from itertools import cycle
import json
from pathlib import Path
import os

import matplotlib.pyplot as plt
import numpy as np

evidence = Path(__file__).resolve().parents[2] / "inputs"
profiles = json.loads((evidence / "budget_profile_inputs.json").read_text())
overlap = json.loads((evidence / "restart_overlap_diagnostic.json").read_text())
fits = json.loads((evidence / "matched_product_fits.json").read_text())
sectors = sorted(fits, key=int)
colors = ["#882255", "#117733", "#332288", "#B25900", "#00729C"]

plt.rcParams.update({"font.size": 9, "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8, "axes.spines.top": False, "axes.spines.right": False})
fig, (ax, bx) = plt.subplots(2, 1, figsize=(5.15, 4.8), constrained_layout=True)
ax.axvspan(*overlap["allowed_range"]["overlap"], alpha=.22, color="0.5", label="Shared interval")
# Clip in data coordinates so the exported vector paths end at the edge of the
# displayed likelihood range, even in PDF readers that ignore clipping paths.
ceiling = 6

for sector, color in zip(sectors, cycle(colors)):
    points = np.asarray([p[:2] for p in profiles[sector]["points"] if not p[2]])
    mass, loss = points.T
    crossings = []
    for x1, x2, y1, y2 in zip(mass[:-1], mass[1:], loss[:-1], loss[1:]):
        if (y1 - ceiling) * (y2 - ceiling) < 0:
            crossings.append(x1 + (ceiling-y1) * (x2-x1) / (y2-y1))
    grid = np.unique(np.r_[mass, crossings])
    curve = np.interp(grid, mass, loss)
    curve[curve > ceiling + 1e-8] = np.nan
    ax.plot(grid, curve, lw=1, label=f"S{sector}", color=color)
    keep = loss <= ceiling
    ax.scatter(mass[keep], loss[keep], s=7, color=color)
ax.axhline(2, ls="--", lw=.85, color="0.36", label=r"$\Delta\mathrm{NLL}=2$")
ax.set(ylim=(-.2, 6.2), xlabel="Mass ratio, $q=M_2/M_1$",
       ylabel=r"Profile $\Delta\mathrm{NLL}$")
ax.legend(loc="lower center", bbox_to_anchor=(.5, 1.03), ncol=3, frameon=False)
x = np.arange(len(sectors))
for track, marker, label, offset, color in (
    ("registered_track", "o", "Reference assignment", -.09, "#00729C"),
    ("other_track", "s", "Other assignment", .09, "#882255"),
):
    shifts = [fits[s][track]["q_shift"] for s in sectors]
    bx.scatter(x + offset, shifts, marker=marker, label=label, color=color)
bx.axhline(0, lw=.85, color="0.36", label="No extraction shift")
bx.set(xticks=x, xticklabels=[f"S{s}" for s in sectors],
       ylabel="Aperture − QLP mass ratio", xlabel="TESS sector")
bx.legend(loc="lower center", bbox_to_anchor=(.5, 1.02), ncol=3, frameon=False)
for panel, letter in zip((ax, bx), ("(a)", "(b)")):
    panel.text(-.10, 1.01, letter, weight="bold", transform=panel.transAxes)
fig.savefig(os.environ["FIG_OUT"])
