"""Inset for pv-storage-grid.html: one illustrative day of PV output, export and battery power.

Run by the build with $FIG_OUT ending in .svg; replace the synthetic profile with the
paper's data (read it from the paper's inputs, never type numbers here).
"""
import numpy as np
import matplotlib.pyplot as plt
from openlabs_fig import PALETTE, save

hours = np.linspace(0, 24, 289)
pv = np.clip(5.0 * np.sin(np.pi * (hours - 6) / 13), 0, None)
cap = 4.0
charge = np.clip(pv - cap, 0, 2.0)                       # charge what the connection cannot take
energy = np.cumsum(charge) * (hours[1] - hours[0])
discharge = np.where((hours >= 19) & (hours < 19 + energy[-1] / 1.6), 1.6, 0.0)
export = pv - charge + discharge

fig, ax = plt.subplots(figsize=(52 / 25.4, 38 / 25.4))
ax.fill_between(hours, 0, pv, color=PALETTE["yellow"], alpha=0.55, lw=0, label="PV")
ax.plot(hours, export, color=PALETTE["vermilion"], lw=1.1, label="Export")
ax.plot(hours, discharge - charge, color=PALETTE["blue"], lw=1.0, label="Battery")
ax.axhline(cap, color=PALETTE["gray"], lw=0.6, ls=(0, (3, 2)))
ax.text(23.6, cap + 0.15, "cap", color=PALETTE["gray"], va="bottom", ha="right")
ax.axhline(0, color=PALETTE["ink"], lw=0.5)
ax.set_xlim(0, 24)
ax.set_xticks([0, 6, 12, 18, 24])
ax.set_xlabel("Hour")
ax.set_ylabel("MW")
ax.legend(loc="lower left", frameon=False, handlelength=1.2, borderaxespad=0.0, bbox_to_anchor=(0.0, 1.01),
          ncol=3, columnspacing=0.8)
ax.set_ylim(-2.4, 5.6)
save(fig)
