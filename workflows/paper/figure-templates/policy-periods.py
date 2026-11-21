"""Illustrative matched sites before/after a policy change, with contemporaneous controls."""
import numpy as np
import matplotlib.pyplot as plt
import openlabs_fig as olf

fig,ax=plt.subplots(figsize=(5.5,3.1),layout="constrained")
for name,pre,post,color,marker in [
    ("Affected sites",[16,19,21,24],[25,27,32,32],"#237586","o"),
    ("Comparison sites",[14,17,19,22],[17,19,21,23],"#99491d","s")]:
    for x,y in zip(pre,post):
        ax.plot([0,1],[x,y],c=color,alpha=.3,lw=1)
    ax.plot([0,1],[np.mean(pre),np.mean(post)],marker=marker,color=color,lw=2.4,label=name)
ax.set(xticks=[0,1],xticklabels=["Before","After"],xlim=(-.15,1.18),ylabel="Margin (AUD/MWh)",
       title="Matched periods  ·  four sites per group")
ax.legend(loc="upper left",frameon=False)
fig.supxlabel("Illustrative values  ·  mean changes +9 and +2 AUD/MWh; descriptive difference +7.",fontsize=9)
olf.save(fig)
