"""Synthetic vibration RMS, fixed baseline and forecasts for two complete units."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

fig, axes = plt.subplots(3,2,figsize=(7,5.5),sharex="col",sharey="row",layout="constrained")
for col,end in enumerate((100,70)):
    hours = np.arange(end+1)
    amplitude = 1+.02*hours+.0006*np.maximum(hours-40,0)**2*(col+1)
    waves = amplitude[:,None]*np.sin(np.arange(128)*2*np.pi/32)
    hi = np.sqrt(np.mean(waves**2,axis=1))
    axes[0,col].plot(hours,waves[:,8])
    axes[1,col].plot(hours,hi)
    origins = np.arange(20,end,5)
    axes[2,col].plot(origins,100-origins,"o",ms=3,label="Prediction")
    axes[2,col].plot(hours,end-hours,color="black",label="Reference")
    axes[2,col].set_xlabel("Operating time (h)")
    axes[0,col].set_title(f"Unit {col+1} · endpoint {end} h")
for ax,label in zip(axes[:,0],["Acceleration at\nfixed phase (g)","Window RMS (g)","Remaining life (h)"]):
    ax.set_ylabel(label)
axes[2,1].legend(fontsize=8)
fig.suptitle("Synthetic specimens · fixed 100 h life predictor")
olf.save(fig)
