"""Synthetic paired daily net cash; explicit full-year denominator."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

days = np.arange(1,366)
baseline = 75+8*np.sin(2*np.pi*days/365)
delta = np.full(365,2.0)
delta[[35,146,258,343]] = [260,370,310,290]
fig, (cash, concentration) = plt.subplots(1,2,figsize=(7,3.4),layout="constrained")
cash.plot(days,baseline+delta,label="Rule B")
cash.plot(days,baseline,ls="--",label="Rule A")
cash.set(xlabel="Day",ylabel="Net cash (AUD/day)",title="a   Same asset and days")
cash.legend()
concentration.plot(days,np.cumsum(np.sort(delta)[::-1])/sum(delta)*100)
concentration.scatter([4],[sum(sorted(delta)[-4:])/sum(delta)*100])
concentration.set(xscale="log",xlabel="Days ranked by paired gain",ylabel="Cumulative annual gain (%)",title="b   All 365 paired days")
fig.suptitle("Synthetic example · four high-gain days")
olf.save(fig)
