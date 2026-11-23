"""Insets for bearing-testbed.html: "signal" (raw vibration snapshots and the RMS trend) and
"hi" (health indicator, failure threshold, prediction time and the RUL distribution).

Synthetic illustrative data; read the paper's records instead (never type numbers here).
"""
import os

import matplotlib.pyplot as plt
import numpy as np

from openlabs_fig import PALETTE, save, tint

rng = np.random.default_rng(7)
minutes = np.arange(0, 400)
onset = 260
B = 9.6e-5                                      # curvature of the degradation stage
hi = 0.25 + 0.0004 * minutes + np.where(minutes > onset, B * (minutes - onset) ** 2, 0)
hi_obs = hi + rng.normal(0, 0.02, minutes.size)
threshold, tp = 1.6, 305
inset = os.environ.get("FIG_INSET") or "signal"

if inset == "signal":
    fig, ax = plt.subplots(figsize=(60 / 25.4, 15 / 25.4))
    t = np.linspace(0, 0.05, 1200)
    early = 0.3 * rng.normal(size=t.size)
    late = 0.3 * rng.normal(size=t.size) + 1.4 * (np.sin(2 * np.pi * 162 * t) > 0.995) * rng.normal(1, 0.2, t.size)
    ax.plot(t * 1000, early, color=PALETTE["green"], lw=0.5)
    ax.plot(t * 1000 + 58, late, color=PALETTE["vermilion"], lw=0.5)
    ax.text(25, 2.75, "early", ha="center", color=PALETTE["green"])
    ax.text(83, 2.75, "near failure", ha="center", color=PALETTE["vermilion"])
    ax.set_ylim(-2.0, 3.3)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("50 ms snapshots", labelpad=1)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    save(fig)
else:
    fig, ax = plt.subplots(figsize=(60 / 25.4, 34 / 25.4))
    seen = minutes <= tp
    ax.plot(minutes[seen], hi_obs[seen], ".", ms=1.2, color=PALETTE["gray"])
    future = np.arange(tp, 460)
    crossings = []
    for k in range(40):  # degradation paths sampled from the fitted model
        b = rng.normal(B, 1.6e-5)
        path = hi[tp] + 0.0004 * (future - tp) + b * ((future - onset) ** 2 - (tp - onset) ** 2)
        crossings.append(future[np.argmax(path >= threshold)] if (path >= threshold).any() else future[-1])
        keep = path <= threshold + 0.05
        ax.plot(future[keep], path[keep], color=tint(PALETTE["blue"], 0.35), lw=0.4)
    ax.axhline(threshold, color=PALETTE["vermilion"], lw=0.8, ls=(0, (3, 2)))
    ax.text(5, threshold + 0.04, "failure threshold", color=PALETTE["vermilion"], va="bottom")
    ax.axvline(tp, color=PALETTE["ink"], lw=0.6)
    ax.text(tp - 4, 1.95, "$t_p$", ha="right", va="top")
    density, edges = np.histogram(crossings, bins=14, range=(340, 410), density=True)
    ax.fill_between(edges[:-1], threshold, threshold + 0.3 * density / density.max(), step="post",
                    color=PALETTE["blue"], alpha=0.6, lw=0)
    median = float(np.median(crossings))
    ax.annotate("", (median, 0.45), (tp, 0.45), arrowprops=dict(arrowstyle="<->", lw=0.6, color=PALETTE["blue"]))
    ax.text((tp + median) / 2, 0.40, "RUL", ha="center", va="top", color=PALETTE["blue"])
    ax.set_xlim(0, 420)
    ax.set_ylim(0.15, 2.05)
    ax.set_xlabel("Minutes in test")
    ax.set_ylabel("Health indicator")
    save(fig)
