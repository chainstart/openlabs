"""<one sentence: what the reader should see in this figure>."""
import matplotlib.pyplot as plt  # noqa: F401  (style already applied by the build)

import openlabs_fig as olf

fig = olf.figure("single", 2.2)
ax = fig.add_subplot(111)
ax.plot([0, 1, 2], [0, 1, 0.5], color=olf.PALETTE["blue"])
ax.set_xlabel("x (unit)")
ax.set_ylabel("y (unit)")
olf.save(fig)  # writes $FIG_OUT
