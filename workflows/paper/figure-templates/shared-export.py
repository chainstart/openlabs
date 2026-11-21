"""One AC-coupled solar/storage interval, measured at the shared meter."""
import matplotlib.pyplot as plt
import openlabs_fig as olf

fig,(a,b) = plt.subplots(1,2,figsize=(7,3.1),layout="constrained")
fig.suptitle("Worked 5-minute dispatch  ·  PV 8 MWac, battery 2 MW / 4 MWh")
a.set(xlim=(0,10),ylim=(0,10),title="a   Power at the common bus")
for start,end,label in [((1,5),(5,5),"PV   7 MW"),((5,5),(9,5),"Grid   5 MW"),
                        ((5,5),(5,1),"Charge   2 MW")]:
    a.annotate("",end,start,arrowprops=dict(arrowstyle="-|>",lw=3,color="#237586"))
    x,y = [(i+j)/2 for i,j in zip(start,end)]
    a.text(x,y+.6,label,ha="center" if y==5 else "left")
a.plot(5,5,"ko")
a.text(5,8,"Export limit   5 MW",ha="center")
a.axis("off")
b.barh([0,1],[5,5],color="#237586",label="Export")
b.barh([0,1],[0,2],left=5,color="#cc9342",label="Charge")
b.barh([0,1],[2,0],left=[5,7],color=".72",label="Curtail")
b.set(yticks=[0,1],yticklabels=["PV only","With storage"],xlabel="Available PV allocated (MW)",
      title="b   Same sunlight and meter limit",ylim=(-.7,1.95))
b.legend(loc="upper center",bbox_to_anchor=(.5,1.0),ncol=3,fontsize=7)
fig.supxlabel("At 96% charging efficiency, stored energy rises from 2.00 to 2.16 MWh.",fontsize=9)
olf.save(fig)
