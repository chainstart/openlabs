"""Illustrative fixed dispatch, lossless, one hour per step, no grid charging."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

hour = np.arange(6)
pv = np.array([0,2,5,5,2,0])
battery = np.array([0,0,-2,-2,2,2])
soc = np.cumsum(-battery)
price = np.array([30,25,10,15,80,95])
shared = np.minimum(pv+battery,3)
separate = np.minimum(pv+np.minimum(battery,0),3)+np.maximum(battery,0)
fig, axes = plt.subplots(3,sharex=True,figsize=(6,5),layout="constrained")
axes[0].plot(hour,pv,"o-",label="PV")
axes[0].plot(hour,battery,"s--",label="Battery (+ discharge)")
axes[0].set(ylabel="Power (MW)")
axes[1].step(hour,soc,where="mid",label="Stored energy")
axes[1].set(ylabel="End SOC (MWh)")
for export,label,marker in ((separate,"Separate meters","o-"),(shared,"Shared 3 MW","x--")):
    axes[2].plot(hour,price*export,marker,label=label)
axes[2].set(xlabel="Hour (1 h intervals)",ylabel="Cash (AUD)")
for ax in axes:
    ax.legend(fontsize=8,loc="upper left")
fig.suptitle("Synthetic replay · PV meter capped at 3 MW\nHourly prices (AUD/MWh): 30, 25, 10, 15, 80, 95")
olf.save(fig)
