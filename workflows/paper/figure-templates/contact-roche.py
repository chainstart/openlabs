"""Illustrative synchronous circular contact binary, in separation and total-mass units."""
import numpy as np
from scipy.optimize import brentq
import matplotlib.pyplot as plt
import openlabs_fig as olf

q = 0.32
mu = q / (1 + q)
inc = np.deg2rad(86)


def potential(x, y, z):
    return ((1 - mu) / np.sqrt((x + mu)**2 + y*y + z*z)
            + mu / np.sqrt((x - 1 + mu)**2 + y*y + z*z) + (x*x + y*y)/2)


def derivative(x):
    return (x - (1-mu)*(x+mu)/abs(x+mu)**3
            - mu*(x-1+mu)/abs(x-1+mu)**3)


neck = brentq(derivative, -mu+.001, 1-mu-.001)
outer = brentq(derivative, 1-mu+.001, 2)
level = .88*potential(neck, 0, 0) + .12*potential(outer, 0, 0)
left = brentq(lambda x: potential(x, 0, 0)-level, -1, -mu-.001)
right = brentq(lambda x: potential(x, 0, 0)-level, 1-mu+.001, outer)


def projection(phase, n, secondary_only=False):
    # Orthographic rays, sampled from observer to photosphere. Clip the exterior branch.
    angle = 2*np.pi*phase
    u, v = np.meshgrid(np.linspace(-1.2, 1.2, 2*n+1), np.linspace(-.6, .6, n+1))
    pixels = np.zeros_like(u)
    for depth in np.linspace(1.25, -1.25, 160):
        along = depth*np.sin(inc) - v*np.cos(inc)
        x = along*np.cos(angle) - u*np.sin(angle)
        y = along*np.sin(angle) + u*np.cos(angle)
        z = depth*np.cos(inc) + v*np.sin(inc)
        inside = (x >= left) & (x <= right) & (np.abs(y)<.6) & (potential(x,y,z)>=level)
        if secondary_only:
            inside &= x >= neck
        visible = inside & (pixels == 0)
        pixels[visible] = np.where(x[visible] < neck, 1., .78)
    return pixels


fig = plt.figure(figsize=(7.0, 4.8), layout="constrained")
axes = fig.subplots(2, 2)
a,b,c,d = axes.flat
x,y = np.meshgrid(np.linspace(left-.04,right+.04,500),np.linspace(-.62,.62,260))
a.contourf(x,y,potential(x,y,0),levels=[level,1e6],colors=["#a6d5dc"])
a.plot([-mu,1-mu],[0,0],"ko",ms=3)
a.plot(0,0,"k+",ms=9,label="Barycentre")
for xpos,label in [(-mu,"$M_1$"),(1-mu,"$M_2$")]:
    a.text(xpos,.06,label,ha="center")
a.legend(frameon=False,loc="upper right",fontsize=8)
a.set(aspect="equal",xlabel="x / separation",ylabel="y / separation",title="a   Common Roche envelope")
b.plot([-1,1],[0,0],color=".6")
for dx,dz,label in [(0,.9,"Orbit normal"),(.95*np.sin(inc),.95*np.cos(inc),"Observer")]:
    b.annotate("",(dx,dz),(0,0),arrowprops=dict(arrowstyle="->"))
    b.text(dx,dz+.04,label,ha="center")
arc = np.linspace(0,inc)
b.plot(.4*np.sin(arc),.4*np.cos(arc))
b.text(.39,.33,"i = 86°")
b.set(xlim=(-.55,1.35),ylim=(-.18,1.2),aspect="equal",title="b   View at conjunction")
b.axis("off")
for offset,phase in [(0,0),(1.1,.5)]:
    pixels = projection(phase,90)
    xs = np.linspace(-1.2,1.2,pixels.shape[1])
    ys = offset + np.linspace(-.6,.6,pixels.shape[0])
    c.contourf(xs,ys,pixels>0,levels=[.5,1.5],colors=["#246880"])
    if np.any(pixels == .78):
        c.contourf(xs,ys,pixels == .78,levels=[.5,1.5],colors=["#bb793b"])
    if phase == .5:
        hidden = projection(phase,90,secondary_only=True)
        assert not np.any(pixels == .78), "Chosen inclination does not produce totality"
        c.contour(xs,ys,hidden,levels=[.4],colors="white",linestyles="--",linewidths=.7)
    c.text(.64,offset,"0.00\ntransit" if phase==0 else "0.50\nhidden limb",va="center")
c.set_aspect("equal")
c.set(title="c   Sky projections",xlim=(-1.25,1.25),ylim=(-.62,1.72))
c.axis("off")
phase = np.linspace(0,.5,55)
flux = np.array([projection(p,50).sum() for p in phase])
flux /= flux.max()
d.plot(np.r_[phase,1-phase[-2::-1]],np.r_[flux,flux[-2::-1]],color="#246880")
d.set(xlabel="Orbital phase",ylabel="Relative flux",title="d   Primary (0) and secondary (0.5) minima")
fig.suptitle("Contact geometry  ·  illustrative q = 0.32, fill-out = 0.12\n"
             "Uniform intensity on each side of the neck, J$_2$/J$_1$ = 0.78",fontsize=11)
olf.save(fig)
