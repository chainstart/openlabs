"""Display frozen estimates; no new hypotheses, thresholds or model fits."""
from common import *
import numpy as np,pandas as pd
os.environ['MPLCONFIGDIR']=str(ART/'mplconfig')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

accs=['GSE184316','GSE199949','GSE150910']
results={a:json.loads((ART/f'{a}_analysis.json').read_text()) for a in accs}
names=['abundance_ECM','abundance_alveolar','abundance_balance','singscore_ECM','singscore_alveolar','singscore_bidirectional']
labels=['ECM','Alveolar','Balance','Rank ECM','Rank alveolar','Rank balance']
rows=[]
for a,r in results.items():
 for name,e in r['by_score'].items():
  for dx,g in e['regional'].items():
   v=g.get('exact_pair_event',g['mean_pair_event_frequency'])
   rows.append(dict(accession=a,score=name,diagnosis=dx,metric='regional_event_frequency',value=v.get('proportion',v.get('mean')),low=v['ci95'][0],high=v['ci95'][1],n=g['donors'],margin=e['regional_threshold']))
   rows.append(dict(accession=a,score=name,diagnosis=dx,metric='ICC1',value=g['icc1'],low=g['icc1_ci95'][0],high=g['icc1_ci95'][1],n=g['donors'],margin=np.nan))
  for adjustment,v in e['disease_effect'].items():
   if v.get('status','estimated')!='estimated':continue
   rows.append(dict(accession=a,score=name,diagnosis='IPF-Control',metric=adjustment,value=v.get('difference',v.get('disease_coefficient')),low=v['ci95'][0],high=v['ci95'][1],n=v.get('n',v.get('n_ipf',0)+v.get('n_control',0)),margin=np.nan))
tab=pd.DataFrame(rows);tab.to_csv(ART/'all_estimates.csv',index=False)
plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':160})
fig,axes=plt.subplots(2,3,figsize=(16,9),constrained_layout=True)
ax=axes[0,0]
pairs=pd.read_csv(ART/'GSE184316_regional_pairs.csv');pairs=pairs[pairs.diagnosis.eq('IPF')&pairs.score.eq('abundance_balance')]
for i,(donor,g) in enumerate(pairs.groupby('donor_id')):
 ax.scatter(np.full(len(g),i),g.abs_difference,s=23,alpha=.65,color='#335c81')
ax.axhline(1,color='#a33',ls='--',label='Frozen margin = 1');ax.set(xlabel='Adult IPF donor (n=10)',ylabel='Absolute regional balance difference',title='A. Development: six pairs per donor')
ax.set_xticks(range(10));ax.set_xticklabels([d.rsplit('_',1)[-1] for d in pairs.donor_id.unique()],rotation=45);ax.legend(frameon=False)
ax=axes[0,1]
m=pd.read_csv(ART/'GSE199949_scores.csv');m=m[m.eligible_adult&m.diagnosis.eq('IPF')]
for donor,g in m.groupby('donor_id'):
 p=g.set_index('region').loc[['central','peripheral']];ax.plot([0,1],p.abundance_balance,'o-',lw=1,alpha=.7,label=donor.rsplit('_',1)[-1])
ax.set(xticks=[0,1],xticklabels=['Central','Peripheral'],ylabel='ECM minus alveolar score',title='B. Confirmation: one pair per adult (n=9)')
ax=axes[0,2]
sub=tab[tab.metric.eq('regional_event_frequency')&tab.score.eq('abundance_balance')&tab.diagnosis.eq('IPF')]
for i,(_,r) in enumerate(sub.iterrows()):
 ax.errorbar(r.value,i,xerr=[[max(0,r.value-r.low)],[max(0,r.high-r.value)]],fmt='o',capsize=3,color='#335c81')
ax.axvline(.25,color='#a33',ls='--');ax.set(yticks=[0,1],yticklabels=['4-core development','Central/peripheral confirm'],xlim=(-.02,1.02),xlabel='Pair-event frequency and 95% interval',title='C. Distinct sampling designs; no pooling')
ax=axes[1,0];colors=['#335c81','#c27330','#48855f']
for i,a in enumerate(accs):
 sub=tab[tab.accession.eq(a)&tab.metric.eq('unadjusted')&tab.score.isin(names[:3])]
 for j,name in enumerate(names[:3]):
  r=sub[sub.score.eq(name)].iloc[0];ax.errorbar(j+(i-1)*.18,r.value,yerr=[[max(0,r.value-r.low)],[max(0,r.high-r.value)]],fmt='o',capsize=3,color=colors[i],label=a if j==0 else None)
ax.axhline(0,color='gray',lw=.8);ax.set(xticks=[0,1,2],xticklabels=labels[:3],ylabel='Donor-mean IPF minus control',title='D. Within-study effects; 95% donor bootstrap');ax.legend(frameon=False,fontsize=8)
ax=axes[1,1]
for i,a in enumerate(accs[:2]):
 sub=tab[tab.accession.eq(a)&tab.metric.eq('ICC1')&tab.diagnosis.eq('IPF')]
 for j,name in enumerate(names):
  r=sub[sub.score.eq(name)].iloc[0];ax.errorbar(r.value,j+(i-.5)*.2,xerr=[[max(0,r.value-r.low)],[max(0,r.high-r.value)]],fmt='o',capsize=2,color=colors[i],label=a if j==0 else None)
ax.axvline(0,color='gray',lw=.8);ax.set(yticks=range(6),yticklabels=labels,xlabel='ICC1 and donor-bootstrap interval',title='E. Conditional regional consistency');ax.legend(frameon=False,fontsize=8)
ax=axes[1,2]
for i,a in enumerate(accs[:2]):
 sub=tab[tab.accession.eq(a)&tab.metric.eq('regional_event_frequency')&tab.diagnosis.eq('IPF')]
 for j,name in enumerate(names):
  r=sub[sub.score.eq(name)].iloc[0];ax.errorbar(r.value,j+(i-.5)*.2,xerr=[[max(0,r.value-r.low)],[max(0,r.high-r.value)]],fmt='o',capsize=2,color=colors[i])
ax.set(yticks=range(6),yticklabels=labels,xlim=(-.02,1.02),xlabel='Event frequency at each frozen margin',title='F. Baselines: margins are not equivalent')
fig.suptitle('Prespecified ECM/alveolar programme: group effects and regional discrepancy\nObservational reanalysis; selected explant regions; no clinical or cell-state attribution',fontsize=13)
for ext in ['png','pdf','svg']:fig.savefig(ART/f'regional_programme_results.{ext}')
atomic(ART/'figure_record.json',dict(at=now(),script_sha256=sha(Path(__file__)),estimate_table_sha256=sha(ART/'all_estimates.csv'),no_new_models=True,notes=['All6pairs per development donor are displayed, but inference uses10donors','Confirmation includes9known-adultIPFdonors; no imputation','Rank and abundance event margins not equivalent','No pooling across cohorts']))
print('Saved estimates and figures')
