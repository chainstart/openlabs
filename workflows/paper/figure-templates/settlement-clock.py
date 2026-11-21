"""Two settlement rules applied to the same illustrative dispatch and prices."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

prices = np.array([62,58,71,940,85,66])
power = np.array([0,-1,0,.85,0,0])
fig,(a,b) = plt.subplots(2,1,sharex=True,figsize=(5.8,3.8),layout="constrained")
minutes = np.arange(5,31,5)
a.bar(minutes-2.5,prices,width=4.6,color="#237586")
a.axhline(prices.mean(),ls="--",color="#934518",label=f"30-min mean  {prices.mean():.1f}")
a.legend()
a.set(ylabel="Price (AUD/MWh)",title="a   Six dispatch prices within one settlement window")
b.bar(minutes-2.5,power,width=4.6,color=np.where(power<0,"#934518","#237586"))
b.axhline(0,color=".4",lw=.7)
b.set(xlabel="Minutes since start of window",ylabel="Export (MW)",xticks=np.arange(0,31,5),
      title="b   Charge then discharge, 85% round-trip efficiency")
fig.supxlabel(f"Illustrative margin per event   ·   5-min AUD {prices@power/12:.2f}    |    "
              f"30-min AUD {prices.mean()*power.sum()/12:.2f}",fontsize=10)
olf.save(fig)
