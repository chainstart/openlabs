"""Scientific figure from frozen evaluation outputs; no model fitting."""
from common import *
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

r=json.loads((ART/'confirmation-results.json').read_text())
names=list(r['all_baselines'])
fig,axes=plt.subplots(1,2,figsize=(11,5),layout='constrained')
for ax,end,title in zip(axes,['target_fit_auc','target_raw_auc'],['Target fit: repeats X1/X2','Measured response: held-out X3']):
    for i,name in enumerate(names):
        d=r['all_baselines'][name][end];v=d['macro_drug_mae'];lo,hi=d['two_way_ci95']
        ax.errorbar(v,i,xerr=np.array([[v-lo],[hi-v]]),fmt='o',color='#b23030' if name=='hgb_full' else '#2d5d7b',capsize=3)
    ax.set_yticks(range(len(names)),names);ax.invert_yaxis();ax.set_xlabel('Macro-drug MAE (95% drug/cell bootstrap CI)');ax.set_title(title);ax.grid(axis='x',alpha=.2)
fig.suptitle('PRISM same-pair assay translation: 50 structures, 178 cell models\nTechnical redo within one screening program; not clinical validation',fontsize=11)
fig.savefig(ART/'all-baseline-errors.png',dpi=160);fig.savefig(ART/'all-baseline-errors.svg');plt.close(fig)
fig,ax=plt.subplots(figsize=(8,3),layout='constrained')
cases=[('Primary: bounded X3',r['primary']['misalignment'],r['primary']['misalignment_ci95']),('Unclipped X3 sensitivity',r['sensitivity']['unclipped_misalignment'],r['sensitivity']['unclipped_misalignment_ci95'])]
for i,(name,v,ci) in enumerate(cases):ax.errorbar(v,i,xerr=np.array([[v-ci[0]],[ci[1]-v]]),fmt='o',capsize=4,color='#2d5d7b')
ax.axvline(0,color='grey',lw=1);ax.axvline(.02,color='#b23030',ls='--',label='Frozen material-overstatement threshold = 0.02')
ax.set_yticks([0,1],[c[0] for c in cases]);ax.invert_yaxis();ax.set_xlim(-.015,.025);ax.set_xlabel('Fitted-label gain minus measured-response gain (HGB vs identity-fit)');ax.legend(loc='lower right',fontsize=8);ax.set_title('Primary hypothesis not supported');fig.savefig(ART/'primary-contrast.png',dpi=160);fig.savefig(ART/'primary-contrast.svg');plt.close(fig)
