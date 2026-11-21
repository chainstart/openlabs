"""Split physical units before constructing overlapping windows."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

fig,(a,b)=plt.subplots(1,2,figsize=(7,3.4),layout="constrained")
for low,high,label,color in [(0,12,"Train · 12","#227586"),(12,16,"Tune · 4","#a95520"),
                             (16,20,"Holdout · 4","#684877")]:
    units=np.arange(low,high)
    a.scatter(units%5,units//5,s=210,marker="s",color=color,label=label)
    for unit in units:
        a.text(unit%5,unit//5,str(unit+1),ha="center",va="center",color="white",fontsize=8)
a.set(title="a   Assign each specimen once",aspect="equal",ylim=(3.6,-.6))
a.axis("off")
a.legend(loc="upper center",bbox_to_anchor=(.5,0),ncol=3,fontsize=7,frameon=False)
for row in range(4):
    start=row*.5
    b.broken_barh([(start,1)],(row-.25,.5),facecolors="#227586")
b.set(yticks=range(4),yticklabels=["W1","W2","W3","W4"],xlabel="Time within one specimen (s)",
      title="b   Window after allocation",ylim=(3.6,-.6))
fig.supxlabel("Illustrative design  ·  1 s windows, 0.5 s stride  ·  score and resample by held-out specimen",fontsize=9)
olf.save(fig)
