from common import *
guard_check()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
r=json.loads((ART/'analysis/test-results-corrected.json').read_text())['contexts']
fig,ax=plt.subplots(figsize=(8,3.7),constrained_layout=True)
cs=['klein_wt','tovar_ins','tovar_scp1'];labels=['Klein WT (435 groups)','Tovar INS (148 groups)','Tovar SCP1 (same study; 148 groups)']
for y,c in zip([2,1,0],cs):
    p=r[c]['primary'];x=100*p['relative_improvement'];lo,hi=np.array(p['relative_CI95'])*100
    color='#1b4965' if c!='tovar_scp1' else '#6b7280'
    ax.errorbar(x,y,xerr=[[x-lo],[hi-x]],fmt='o',color=color,capsize=4,markersize=6,lw=1.7)
    ax.text(13.3,y,f'{x:+.1f}% [{lo:.1f}, {hi:.1f}]',va='center',ha='left',fontsize=9)
ax.axvline(0,color='#9ca3af',lw=1);ax.axvline(10,color='#bc6c25',ls='--',lw=1.3)
ax.text(10,2.46,'10% minimum\nrelative benefit',ha='center',va='bottom',fontsize=9,color='#8d4d15')
ax.set_yticks([2,1,0],labels);ax.set_xlim(-20,31);ax.set_ylim(-.55,2.95)
ax.set_xticks([-20,-10,0,10]);ax.set_xlabel('Relative reduction in half-coverage transfer MSE (%)\nPositive values favor adding source replicate precision')
ax.set_title('No registered practical gain from source replicate precision',loc='left',fontsize=12,pad=18)
ax.spines[['top','right','left']].set_visible(False);ax.grid(axis='x',alpha=.15)
fig.text(.01,-.05,'95% paired locus-group bootstrap intervals; conditional on frozen models.\nSCP1 is corroboration within Tovar, not a third independent experiment.',fontsize=9)
out=ART/'figures';out.mkdir(exist_ok=True)
for ext in ['svg','png','pdf']:fig.savefig(out/('primary-risk-precision.'+ext),dpi=180,bbox_inches='tight')
plt.close(fig)
write(DATA/'figure-provenance.json',dict(time=now(),source_results_sha256=sha(ART/'analysis/test-results-corrected.json'),files={p.name:sha(p) for p in out.iterdir()}))
