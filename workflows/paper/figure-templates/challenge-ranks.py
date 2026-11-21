"""Synthetic ranks; source ordering A–H; pair counts use strict inversions."""
import matplotlib.pyplot as plt
import numpy as np
import openlabs_fig as olf

ranks = np.array([[1,2,3,4,5,6,7,8],[2,1,3,4,5,6,8,7],[3,2,1,5,4,6,7,8],
                  [1,3,2,4,6,5,7,8],[5,4,3,2,1,6,7,8]])
fig,(matrix,pairs)=plt.subplots(1,2,figsize=(7,3.5),layout="constrained",width_ratios=(2,1))
matrix.imshow(ranks,cmap="Blues",vmin=1,vmax=8,aspect="auto")
for (i,j),v in np.ndenumerate(ranks):
    matrix.text(j,i,str(v),ha="center",va="center",color="white" if v>5 else "black")
matrix.set(xticks=range(8),xticklabels=list("ABCDEFGH"),yticks=range(5),yticklabels=range(1,6),
           xlabel="Models in source rank order",ylabel="Challenge",title="a   Target rank (1 = best)")
counts=[sum(row[i]>row[j] for i in range(8) for j in range(i+1,8)) for row in ranks]
pairs.barh(range(5),counts)
pairs.set(ylim=(4.5,-.5),yticks=range(5),yticklabels=range(1,6),xlabel="Reversed pairs / 28",title="b   Strict inversions")
fig.suptitle("Synthetic ranks · A and B reverse in challenges 2, 3 and 5")
olf.save(fig)
