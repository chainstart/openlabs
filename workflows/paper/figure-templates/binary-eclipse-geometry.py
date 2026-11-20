"""Eclipsing-binary geometry and how it forms the light curve.

(a) the orbit seen from above the orbital plane with the line of sight; (b) the
same orbit projected on the sky at inclination i; (c) the light curve computed
from that geometry (two uniform discs). Numbered phases 1-4 are the same
configurations in all three panels, so the reader can follow each dip back to
its geometry. Replace the parameters with the system's fitted values.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch

import openlabs_fig as olf

# ---- system (units of the primary radius); fitted values go here
R1, R2 = 1.0, 0.62          # radii
A = 4.2                     # separation
INC = np.radians(84.0)      # inclination
J = 0.45                    # surface-brightness ratio star 2 / star 1
Q = 0.55                    # mass ratio M2/M1 (sets the barycentre)


def overlap(d, r1, r2):
    """Area of intersection of two discs with centre distance d."""
    d = np.asarray(d, float)
    out = np.zeros_like(d)
    full = d <= abs(r1 - r2)
    out[full] = np.pi * min(r1, r2) ** 2
    part = (d > abs(r1 - r2)) & (d < r1 + r2)
    dd = d[part]
    a1 = r1 ** 2 * np.arccos((dd ** 2 + r1 ** 2 - r2 ** 2) / (2 * dd * r1))
    a2 = r2 ** 2 * np.arccos((dd ** 2 + r2 ** 2 - r1 ** 2) / (2 * dd * r2))
    a3 = 0.5 * np.sqrt((-dd + r1 + r2) * (dd + r1 - r2) * (dd - r1 + r2) * (dd + r1 + r2))
    out[part] = a1 + a2 - a3
    return out


phase = np.linspace(-0.25, 1.25, 3000)
theta = 2 * np.pi * phase                     # phase 0: star 2 in front (primary eclipse)
# relative position of star 2 w.r.t. star 1; observer along -z (towards the viewer)
x = A * np.sin(theta)
z_orb = -A * np.cos(theta)                    # >0: star 2 behind star 1 along the line of sight
y_sky = A * np.cos(theta) * np.cos(INC)
d_sky = np.hypot(x, y_sky)
L1, L2 = np.pi * R1 ** 2, J * np.pi * R2 ** 2
lost = overlap(d_sky, R1, R2)
flux = np.where(z_orb < 0, L1 + L2 - lost, L1 + L2 - J * lost)   # front star hides part of the back one
flux /= L1 + L2

marks = {1: 0.0, 2: 0.25, 3: 0.5, 4: 0.75}
c1, c2 = olf.PALETTE["orange"], olf.PALETTE["blue"]

fig = olf.figure("double", 2.35)
gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.15, 1.55])
ax_top, ax_sky, ax_lc = (fig.add_subplot(gs[0, k]) for k in range(3))

# ---- (a) top view: barycentric orbits and the line of sight
m1, m2 = Q / (1 + Q), 1 / (1 + Q)              # fraction of separation from barycentre
t = np.linspace(0, 2 * np.pi, 400)
ax_top.plot(m1 * A * np.cos(t), m1 * A * np.sin(t), color=c1, lw=0.7, ls=(0, (2, 1.5)))
ax_top.plot(m2 * A * np.cos(t), m2 * A * np.sin(t), color=c2, lw=0.7, ls=(0, (2, 1.5)))
for k, ph in marks.items():
    th = 2 * np.pi * ph
    rel = np.array([np.sin(th), -np.cos(th)]) * A     # star 2 relative to star 1 in (x, z)
    p1, p2 = -m1 * rel, m2 * rel
    ax_top.add_patch(Circle(p2, R2 * 0.55, color=c2, alpha=0.9 if k == 1 else 0.35, lw=0))
    ax_top.text(*(p2 * 1.32), str(k), ha="center", va="center", fontsize=7, fontweight="bold")
ax_top.add_patch(Circle((0, 0), 0.07, color=olf.PALETTE["ink"]))
ax_top.add_patch(Circle(-m1 * np.array([0, -A]), R1 * 0.55, color=c1, lw=0))
ax_top.add_patch(FancyArrowPatch((0, -m2 * A - 1.2), (0, -m2 * A - 3.0), arrowstyle="-|>",
                                 mutation_scale=8, color=olf.PALETTE["ink"], lw=0.8))
ax_top.text(0.35, -m2 * A - 2.6, "to observer", fontsize=6.5, ha="left", va="center")
ax_top.set_xlim(-3.6, 3.6)
ax_top.set_ylim(-6.6, 3.9)
ax_top.set_aspect("equal")
ax_top.axis("off")
ax_top.set_title("a  Orbit from above", fontsize=7.5)

# ---- (b) sky projection
ax_sky.plot(x, y_sky, color=olf.PALETTE["gray"], lw=0.6, ls=(0, (2, 1.5)))
near = np.where(z_orb < 0, y_sky, np.nan)          # near half of the orbit passes in front of star 1
ax_sky.plot(x, near, color=olf.PALETTE["gray"], lw=0.6, ls=(0, (2, 1.5)), zorder=2.5)
ax_sky.add_patch(Circle((0, 0), R1, color=c1, lw=0, zorder=2))
for k, ph in marks.items():
    th = 2 * np.pi * ph
    xs, ys, zs = A * np.sin(th), A * np.cos(th) * np.cos(INC), -A * np.cos(th)
    front = zs < 0
    ax_sky.add_patch(Circle((xs, ys), R2, color=c2, lw=0, alpha=1 if k in (1, 3) else 0.35,
                            zorder=3 if front else 1))
    if not front and k == 3:   # hidden behind star 1: show its outline
        ax_sky.add_patch(Circle((xs, ys), R2, fill=False, lw=0.7, ls=(0, (1.5, 1)), ec=olf.PALETTE["ink"], zorder=4))
    dy = {1: R2 + 0.5, 3: -(R2 + 0.5), 2: R2 + 0.45, 4: R2 + 0.45}[k]
    ax_sky.text(xs, ys + dy, str(k), ha="center", va="center", fontsize=7, fontweight="bold", zorder=5)
ax_sky.text(0, -2.35, f"i = {np.degrees(INC):.0f}°: centres pass {A * np.cos(INC):.2f} R$_1$ apart (a cos i)\n"
            "1 transit: star 2 in front    3 occultation: behind",
            fontsize=6.5, ha="center", va="top", color=olf.PALETTE["ink"])
ax_sky.set_xlim(-5.3, 5.3)
ax_sky.set_ylim(-3.6, 2.4)
ax_sky.set_aspect("equal")
ax_sky.axis("off")
ax_sky.set_title("b  Projected on the sky", fontsize=7.5)

# ---- (c) light curve
ax_lc.plot(phase, flux, color=olf.PALETTE["ink"], lw=1.0)
for k, ph in marks.items():
    f = np.interp(ph, phase, flux)
    ax_lc.plot([ph], [f], "o", ms=3.2, color=c2 if k in (1, 3) else olf.PALETTE["gray"])
    ax_lc.annotate(str(k), (ph, f), xytext=(0, -9 if k in (1, 3) else 6), textcoords="offset points",
                   ha="center", fontsize=7, fontweight="bold")
depth1 = 1 - flux[np.argmin(abs(phase - 0.0))]
depth2 = 1 - flux[np.argmin(abs(phase - 0.5))]
ax_lc.text(0.0, 1 - depth1 - 0.075, f"primary\ndepth {depth1:.2f}", ha="center", va="top", fontsize=6.5)
ax_lc.text(0.5, 1 - depth2 - 0.075, f"secondary\ndepth {depth2:.2f}", ha="center", va="top", fontsize=6.5)
ax_lc.set_xlim(-0.25, 1.25)
ax_lc.set_ylim(1 - depth1 - 0.24, 1.06)
ax_lc.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
ax_lc.set_xlabel("Orbital phase")
ax_lc.set_ylabel("Relative flux")
ax_lc.set_title("c  Resulting light curve", fontsize=7.5)

for ax in (ax_top, ax_sky):
    ax.set_anchor("N")
olf.save(fig)
