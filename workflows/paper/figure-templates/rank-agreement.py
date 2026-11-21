from pathlib import Path
import csv

import matplotlib.pyplot as plt
import openlabs_fig as olf

workspace = Path(__file__).resolve().parents[2]
with (workspace / "inputs/ranks.csv").open() as handle:
    rows = [row for row in csv.DictReader(handle) if row["scenario"] == "primary"]

fig, ax = plt.subplots(figsize=(4.97, 2.55))
labels = {"ottawa": "Ottawa · conditional", "seu_gearbox": "SEU · secondary"}
names = [labels.get(row["rig"], row["rig"].upper()) for row in rows]
for y, row in enumerate(rows):
    point, lower, upper = [float(row[key]) for key in ("rho", "lower", "upper")]
    ax.errorbar(point, y, xerr=[[point - lower], [upper - point]], fmt="o",
                color="#006b8c", capsize=3, linewidth=1.5, zorder=3)

ax.axvline(0.4, color="#494949", lw=1, ls="--", label="Point estimate cutoff (0.4)")
ax.axvline(0.6, color="#494949", lw=1, ls=":", label="Upper bound cutoff (0.6)")
ax.set(yticks=range(len(names)), yticklabels=names, xlim=(-1.02, 1.02),
       ylim=(len(rows)-.4, -.6), xlabel="Spearman rank correlation")
ax.set_xticks([-1, -.5, 0, .5, 1])
ax.xaxis.grid(True, alpha=.2)
ax.tick_params(axis="both", labelsize=9)
ax.tick_params(axis="y", length=0)
ax.xaxis.label.set_size(10)
ax.legend(loc="lower center", bbox_to_anchor=(.5, 1.02), frameon=False, ncol=2, fontsize=8)
fig.supxlabel("Paired percentile intervals · Ottawa block weights · SEU inferred specimens", fontsize=8)
fig.tight_layout(rect=(0,.06,1,1))
olf.save(fig)
