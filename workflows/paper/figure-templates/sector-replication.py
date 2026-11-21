"""Synthetic eclipse-depth recovery under a fixed eclipse shape."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

rng = np.random.default_rng(31)
phase = np.linspace(-.12, .12, 120)
shape = np.clip((.07 - abs(phase)) / .04, 0, 1)
sigma = .006
fig, axes = plt.subplot_mosaic([["flux", "depth"], ["residual", "depth"]],
                               figsize=(7, 3.8), layout="constrained")
axes["residual"].sharex(axes["flux"])
for sector in range(1, 6):
    flux = 1 - .13 * shape + rng.normal(0, sigma, len(phase))
    depth = np.dot(shape, 1-flux) / np.dot(shape, shape)
    model = 1 - depth * shape
    axes["depth"].errorbar(depth, sector, xerr=1.96*sigma/np.linalg.norm(shape), fmt="o", color="C0")
    if sector == 1:
        axes["flux"].scatter(phase, flux, s=5)
        axes["flux"].plot(phase, model, color="black")
        axes["residual"].scatter(phase, flux-model, s=5)
axes["flux"].set(ylabel="Relative flux", title="a   Sector 1")
axes["residual"].set(xlabel="Orbital phase", ylabel="Data − fit")
axes["depth"].set(xlabel="Fractional depth (95% CI)", ylabel="Sector", yticks=range(1,6), title="b   All sectors")
fig.suptitle("Synthetic example · fixed trapezoid, known noise")
olf.save(fig)
