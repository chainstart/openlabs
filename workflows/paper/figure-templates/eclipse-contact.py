"""Circular edge-on transit of a dark disk over a uniformly bright disk."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

radius, separation = .4, 5
phase = np.linspace(-.07,.07,301)
distance = abs(separation*np.sin(2*np.pi*phase))
area = np.zeros_like(distance)
area[distance <= 1-radius] = np.pi*radius**2
partial = (distance > 1-radius) & (distance < 1+radius)
d = distance[partial]
a = np.arccos((d*d+1-radius**2)/(2*d))
b = np.arccos((d*d+radius**2-1)/(2*d*radius))
area[partial] = a + radius**2*b - d*np.sin(a)
model = 1-area/np.pi
flux = model + np.random.default_rng(7).normal(0,.003,len(phase))
fig, (geometry, light, residual) = plt.subplots(3,figsize=(6,5),layout="constrained")
for x, size, color in ((0,1,"goldenrod"), (0,radius,"black")):
    geometry.add_patch(plt.Circle((x,0), size,color=color))
geometry.set(xlim=(-2,2),ylim=(-1.1,1.1),aspect="equal",title="a   Model at conjunction")
geometry.axis("off")
light.scatter(phase,flux,s=4)
light.plot(phase,model,color="black")
light.set(ylabel="Relative flux", title="b   Uniform source, dark occulter")
residual.sharex(light)
residual.scatter(phase,flux-model,s=4)
residual.set(ylabel="Data − model",xlabel="Orbital phase")
for ax in (light,residual):
    for contact in (1-radius,1+radius):
        for sign in (-1,1):
            ax.axvline(sign*np.arcsin(contact/separation)/(2*np.pi),ls=":",color=".45")
fig.suptitle("Synthetic eclipse · dotted lines mark contacts")
olf.save(fig)
