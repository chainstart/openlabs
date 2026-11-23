"""Insets for contact-binary.html, computed from a Roche model (illustrative parameters).

$FIG_INSET selects the drawing: "roche" (equatorial section of the common envelope with the
inner and outer critical points), "phases" (sky projections at four phases) or "lc" (the
light curve those projections produce). Units: separation a = 1, total mass = 1.
Replace q, the fill-out and the inclination with the paper's fitted values.
"""
import os

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import brentq

from openlabs_fig import PALETTE, save, tint

Q, FILL, INC = 0.32, 0.12, np.deg2rad(82.0)
T_RATIO = 0.86                        # secondary / primary surface brightness
MU = Q / (1 + Q)
PHASES = (0.0, 0.25, 0.5, 0.75)


def potential(x, y, z):
    return ((1 - MU) / np.sqrt((x + MU) ** 2 + y * y + z * z)
            + MU / np.sqrt((x - 1 + MU) ** 2 + y * y + z * z) + (x * x + y * y) / 2)


def dphi(x):
    return x - (1 - MU) * (x + MU) / abs(x + MU) ** 3 - MU * (x - 1 + MU) / abs(x - 1 + MU) ** 3


L1 = brentq(dphi, -MU + 1e-3, 1 - MU - 1e-3)
L2 = brentq(dphi, 1 - MU + 1e-3, 2.0)
L3 = brentq(dphi, -2.0, -MU - 1e-3)
LEVEL = (1 - FILL) * potential(L1, 0, 0) + FILL * potential(L2, 0, 0)
LEFT = brentq(lambda x: potential(x, 0, 0) - LEVEL, -1.2, -MU - 1e-3)
RIGHT = brentq(lambda x: potential(x, 0, 0) - LEVEL, 1 - MU + 1e-3, L2)


def sky(phase, n=120):
    """Surface brightness on the sky plane (0 = empty): the first envelope point along each
    ray, its component's brightness, and linear limb darkening from the surface normal."""
    angle = 2 * np.pi * phase
    sight = np.array([np.sin(INC) * np.cos(angle), np.sin(INC) * np.sin(angle), np.cos(INC)])
    u, v = np.meshgrid(np.linspace(-1.15, 1.15, 2 * n + 1), np.linspace(-0.6, 0.6, n + 1))
    image = np.zeros_like(u)
    done = np.zeros(u.shape, bool)
    for depth in np.linspace(1.3, -1.3, 400):
        along = depth * np.sin(INC) - v * np.cos(INC)
        x = along * np.cos(angle) - u * np.sin(angle)
        y = along * np.sin(angle) + u * np.cos(angle)
        z = depth * np.cos(INC) + v * np.sin(INC)
        inside = ((x >= LEFT) & (x <= RIGHT) & (np.abs(y) < 0.7) & (np.abs(z) < 0.7)
                  & (potential(x, y, z) >= LEVEL))
        hit = inside & ~done
        if hit.any():
            px, py, pz, h = x[hit], y[hit], z[hit], 1e-4
            grad = np.stack([(potential(px + h, py, pz) - potential(px - h, py, pz)),
                             (potential(px, py + h, pz) - potential(px, py - h, pz)),
                             (potential(px, py, pz + h) - potential(px, py, pz - h))])
            normal = -grad / np.linalg.norm(grad, axis=0)
            cosine = np.clip(np.tensordot(sight, normal, axes=1), 0, 1)
            image[hit] = np.where(px < L1, 1.0, T_RATIO) * (1 - 0.6 * (1 - cosine))
            done |= hit
    return image, u, v


inset = os.environ.get("FIG_INSET") or "roche"

if inset == "roche":
    fig, ax = plt.subplots(figsize=(62 / 25.4, 34 / 25.4))
    x, y = np.meshgrid(np.linspace(-1.0, 1.45, 700), np.linspace(-0.7, 0.7, 400))
    phi = potential(x, y, 0)
    phi[np.hypot(x - 0.15, y) > 1.25] = np.nan          # keep the inner lobes, drop the outer branch
    ax.contourf(x, y, phi, levels=[LEVEL, 1e9], colors=[tint(PALETTE["sky"], 0.45)])
    ax.contour(x, y, phi, levels=[LEVEL], colors=[PALETTE["blue"]], linewidths=0.9)
    ax.contour(x, y, phi, levels=[potential(L1, 0, 0)], colors=[PALETTE["gray"]], linewidths=0.6,
               linestyles=[(0, (3, 2))])
    ax.contour(x, y, phi, levels=[potential(L2, 0, 0)], colors=[PALETTE["gray"]], linewidths=0.5,
               linestyles=[(0, (1, 1.5))])
    for xpos, name in ((-MU, "$M_1$"), (1 - MU, "$M_2$")):
        ax.plot(xpos, 0, "o", color=PALETTE["ink"], ms=2.2)
        ax.text(xpos, -0.1, name, ha="center", va="top")
    for xpos, name in ((L1, "L1"), (L2, "L2")):
        ax.plot(xpos, 0, marker="x", color=PALETTE["vermilion"], ms=3.5, mew=0.8)
        ax.text(xpos, 0.09, name, ha="center", va="bottom", color=PALETTE["vermilion"])
    ax.plot(0, 0, "+", color=PALETTE["ink"], ms=5, mew=0.7)
    ax.set_aspect("equal")
    ax.set_xlim(-0.95, 1.4)
    ax.set_ylim(-0.62, 0.62)
    ax.axis("off")
    save(fig)

elif inset == "phases":
    fig, axes = plt.subplots(1, 4, figsize=(104 / 25.4, 16 / 25.4))
    cmap = plt.matplotlib.colors.LinearSegmentedColormap.from_list(
        "star", ["#ffffff", tint(PALETTE["orange"], 0.55), PALETTE["orange"]])
    for ax, phase in zip(axes, PHASES):
        image, u, v = sky(phase, 70)
        ax.contourf(u, v, np.where(image > 0, image, np.nan), levels=np.linspace(0.38, 1.0, 9), cmap=cmap,
                    extend="both")
        ax.contour(u, v, image > 0, levels=[0.5], colors=[PALETTE["ink"]], linewidths=0.5)
        ax.set_aspect("equal")
        ax.set_xlim(-1.15, 1.15)
        ax.set_ylim(-0.6, 0.6)
        ax.axis("off")
    save(fig)

else:  # "lc"
    phases = np.linspace(0, 1, 81)
    flux = np.array([sky(p, 60)[0].sum() for p in phases])
    flux /= flux.max()
    fig, ax = plt.subplots(figsize=(104 / 25.4, 30 / 25.4))
    ax.plot(phases, flux, color=PALETTE["ink"], lw=1.0)
    for phase in PHASES:
        ax.axvline(phase, color=PALETTE["gray"], lw=0.5, ls=(0, (2, 2)))
    ax.annotate("primary minimum", (0.0, flux[0]), (0.07, flux.min() + 0.02), va="bottom",
                arrowprops=dict(arrowstyle="-", lw=0.5, color=PALETTE["gray"]))
    ax.annotate("secondary minimum", (0.5, flux[40]), (0.57, flux[40] + 0.02), va="bottom",
                arrowprops=dict(arrowstyle="-", lw=0.5, color=PALETTE["gray"]))
    ax.set_xlim(-0.02, 1.0)
    ax.set_xticks(PHASES)
    ax.set_xlabel("Orbital phase")
    ax.set_ylabel("Relative flux")
    save(fig)
