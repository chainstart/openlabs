"""Degradation, failure threshold and the definition of remaining useful life.

A health indicator observed up to the prediction time t_p, the model's predictive
band after t_p, the failure threshold, the predicted end-of-life distribution
where the band crosses the threshold, and RUL = t_EOL - t_p. Everything is
computed from a small Monte Carlo degradation model so the band and the
distribution are consistent; replace the model with the paper's own.
"""
import numpy as np

import openlabs_fig as olf

rng = np.random.default_rng(7)
t = np.linspace(0, 1000, 1001)                    # cycles
THRESH, T_P = 0.80, 420                           # failure threshold, prediction time


def capacity(t, a, b):
    return 1.0 - a * (t / 1000) ** b


a_true, b_true = 0.27, 1.6
obs_t = np.arange(0, T_P + 1, 15)
obs = capacity(obs_t, a_true, b_true) + rng.normal(0, 0.006, obs_t.size)

# posterior-like parameter draws around the truth (stand-in for the fitted model)
a_s = rng.normal(a_true, 0.03, 4000)
b_s = rng.normal(b_true, 0.12, 4000)
paths = capacity(t[None, :], a_s[:, None], b_s[:, None])
lo, mid, hi = np.percentile(paths, [5, 50, 95], axis=0)
eol = 1000 * ((1 - THRESH) / a_s) ** (1 / b_s)
eol = eol[np.isfinite(eol)]
eol_true = t[np.argmax(capacity(t, a_true, b_true) < THRESH)]
eol_med = float(np.median(eol))

ink, gray = olf.PALETTE["ink"], olf.PALETTE["gray"]
blue, wine, orange = olf.PALETTE["blue"], olf.PALETTE["wine"], olf.PALETTE["orange"]

fig = olf.figure("onehalf", 3.6)
ax = fig.add_subplot(111)
after = t >= T_P
ax.fill_between(t[after], lo[after], hi[after], color=blue, alpha=0.18, lw=0, label="90% predictive band")
ax.plot(t[after], mid[after], color=blue, lw=1.1, ls=(0, (3, 1.5)), label="predicted median")
ax.plot(obs_t, obs, "o", ms=2.6, color=ink, label="observed")
ax.plot(t, capacity(t, a_true, b_true), color=gray, lw=0.6, alpha=0.6, zorder=0)
ax.axhline(THRESH, color=wine, lw=1.0)
ax.text(8, THRESH - 0.012, "failure threshold (80% capacity)", color=wine, fontsize=6.5, va="top")
ax.axvline(T_P, color=ink, lw=0.6, ls=(0, (1, 1.5)))
ax.text(T_P + 8, 1.012, r"prediction time $t_p$", fontsize=6.5, va="bottom")

# predicted end-of-life density drawn on the threshold line
hist, edges = np.histogram(eol, bins=40, range=(eol.min(), eol.max()), density=True)
centres = 0.5 * (edges[1:] + edges[:-1])
scale = 0.06 / hist.max()
ax.fill_between(centres, THRESH, THRESH - hist * scale, color=orange, alpha=0.75, lw=0,
                label=r"predicted $t_{\mathrm{EOL}}$")
ax.plot([eol_true], [THRESH], marker="v", color=ink, ms=4.5, ls="none")
ax.text(eol_true + 10, THRESH + 0.008, "true EOL", fontsize=6.5, ha="left", va="bottom")

# RUL arrow
y_r = 0.69
ax.annotate("", xy=(eol_med, y_r), xytext=(T_P, y_r),
            arrowprops=dict(arrowstyle="<->", lw=0.8, color=ink, shrinkA=0, shrinkB=0))
ax.text((T_P + eol_med) / 2, y_r + 0.008, rf"RUL $= t_{{\mathrm{{EOL}}}} - t_p \approx {eol_med - T_P:.0f}$ cycles",
        ha="center", va="bottom", fontsize=6.8)
ax.plot([eol_med, eol_med], [y_r, THRESH - 0.065], color=ink, lw=0.5, ls=(0, (1, 1.5)))

ax.set_xlim(0, 1000)
ax.set_ylim(0.66, 1.03)
ax.set_xlabel("Cycle")
ax.set_ylabel("Capacity (fraction of rated)")
ax.legend(loc="lower left", bbox_to_anchor=(0,1.02), ncol=2, fontsize=7, frameon=False)
fig.suptitle("Illustrative degradation model", fontsize=10)
olf.save(fig)
