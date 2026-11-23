"""Insets for isolate-tracing.html: "tree" (hierarchical tree of cgMLST allele distances,
leaves coloured by source) and "attr" (share of human cases attributed to each reservoir).

Synthetic illustrative profiles; read the paper's allele table and model output instead.
"""
import os

import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import dendrogram, linkage
from scipy.spatial.distance import pdist

from openlabs_fig import PALETTE, save

SOURCES = {"Broiler": PALETTE["orange"], "Retail meat": PALETTE["vermilion"],
           "Water": PALETTE["sky"], "Human": PALETTE["ink"]}
rng = np.random.default_rng(11)
centres = rng.integers(0, 6, size=(5, 60))
labels, profiles = [], []
mix = {0: ["Broiler"] * 5 + ["Retail meat"] * 3 + ["Human"] * 4, 1: ["Broiler"] * 4 + ["Human"] * 3,
       2: ["Water"] * 5 + ["Human"] * 1, 3: ["Retail meat"] * 3 + ["Broiler"] * 2 + ["Human"] * 2, 4: ["Water"] * 3}
for k, names in mix.items():
    for name in names:
        p = centres[k].copy()
        flips = rng.random(60) < 0.08
        p[flips] = rng.integers(0, 6, flips.sum())
        profiles.append(p)
        labels.append(name)
profiles = np.array(profiles)
inset = os.environ.get("FIG_INSET") or "tree"

if inset == "tree":
    tree = linkage(pdist(profiles, metric="hamming") * 60, method="average")
    fig, ax = plt.subplots(figsize=(78 / 25.4, 28 / 25.4))
    with plt.rc_context({"lines.linewidth": 0.6}):
        d = dendrogram(tree, ax=ax, color_threshold=0, above_threshold_color=PALETTE["gray"], no_labels=True)
    for x, leaf in zip(np.arange(5, 10 * len(labels), 10), d["leaves"]):
        ax.plot(x, -0.8, "s", ms=3.2, color=SOURCES[labels[leaf]], clip_on=False)
    ax.set_ylim(-1.6, None)
    ax.set_xticks([])
    ax.set_ylabel("Allele differences")
    ax.spines["bottom"].set_visible(False)
    handles = [plt.Line2D([], [], marker="s", ls="", ms=3.2, color=c, label=n) for n, c in SOURCES.items()]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=4, frameon=False,
              handletextpad=0.2, columnspacing=0.9, borderaxespad=0.1)
    save(fig)
else:
    shares = {"Broiler": 0.58, "Retail meat": 0.24, "Water": 0.11, "Unattributed": 0.07}
    lows = {"Broiler": 0.47, "Retail meat": 0.15, "Water": 0.05, "Unattributed": 0.02}
    highs = {"Broiler": 0.69, "Retail meat": 0.33, "Water": 0.18, "Unattributed": 0.13}
    fig, ax = plt.subplots(figsize=(78 / 25.4, 22 / 25.4))
    names = list(shares)[::-1]
    colours = [SOURCES.get(n, PALETTE["light"]) for n in names]
    ax.barh(names, [shares[n] for n in names], color=colours, height=0.62)
    ax.errorbar([shares[n] for n in names], names,
                xerr=[[shares[n] - lows[n] for n in names], [highs[n] - shares[n] for n in names]],
                fmt="none", ecolor=PALETTE["ink"], elinewidth=0.6, capsize=1.5)
    ax.set_xlim(0, 0.8)
    ax.set_xlabel("Share of human cases (95% interval)")
    save(fig)
