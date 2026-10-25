from attribution import *
os.environ['MPLCONFIGDIR']=str(ART/'mplconfig')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

m=json.loads((ART/'development_metrics.json').read_text())['IPF_primary_ECM']['models']
names=['NNLS_healthy','NNLS_pooled','NNLS_IPF','constant']
fig,ax=plt.subplots(figsize=(7,3.4),constrained_layout=True)
for i,n in enumerate(names):
 v=m[n];y=v['mae']*100;lo,hi=np.array(v['ci95'])*100
 ax.errorbar(y,i,xerr=[[y-lo],[hi-y]],fmt='o',capsize=4,color='#355c7d')
ax.set_yticks(range(4),names);ax.invert_yaxis()
ax.set_xlabel('ECM epithelial source-share MAE (percentage points; 95% donor bootstrap CI)')
ax.set_title('Development only: 12 IPF donors, leave-one-donor-out\nPROVISIONAL: original-source count reconciliation failed',fontsize=10)
ax.grid(axis='x',alpha=.2)
for ext in ['png','svg']:fig.savefig(ART/f'development_primary_provisional.{ext}',dpi=180)
