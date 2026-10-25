"""Independent numeric reconstruction from source rows; no scoring/analysis imports.

This reviews the same frozen experiment, not a second confirmation or new model.
"""
from common import *
import csv,gzip,math
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import binom
import statsmodels.api as sm

def reconstruct(acc):
 plan=json.loads((DATA/'plan_frozen_v1.json').read_text())
 fmt=json.loads((DATA/f'{acc}_format_audit.json').read_text())
 ref=json.loads((DATA/'annotation_readonly_reference.json').read_text())
 ann=pd.read_csv(ref['path'],sep='\t')
 ann=ann[ann.ensembl.notna()&ann.GeneName.notna()&ann.ExonLength.gt(0)]
 ann=ann[~ann.GeneName.duplicated(keep=False)].set_index('ensembl')
 mp=pd.read_csv(DATA/f'{acc}_gene_mapping.csv').set_index('source_id').ensembl.to_dict()
 files={'GSE184316':'GSE184316_fHP_Txome_FPKM_RNAseq.csv.gz','GSE199949':'GSE199949_raw.counts.txt.gz','GSE150910':'GSE150910_gene-level_count_file.csv.gz'}
 sample_ids=list(fmt['sample_map']);column_ids=[fmt['header'].index(fmt['sample_map'][s]) for s in sample_ids]
 sums=np.zeros(len(sample_ids));target={g:np.zeros(len(sample_ids)) for gs in plan['programs'].values() for g in gs}
 with gzip.open(ART/'payload'/files[acc],'rt') as f:
  reader=csv.reader(f,delimiter=fmt['delimiter']);next(reader)
  for row in reader:
   if not row:continue
   en=mp.get(row[0])
   if pd.isna(en):continue
   values=np.array([float(row[i]) for i in column_ids])
   if acc!='GSE184316':values=values/float(ann.loc[en,'ExonLength'])
   sums+=values
   symbol=ann.loc[en,'GeneName']
   if symbol in target:target[symbol]+=values
 normalized={g:np.log2(1+v/sums*1e6) for g,v in target.items()}
 score={p:sum(normalized[g] for g in gs)/len(gs) for p,gs in plan['programs'].items()}
 score['balance']=score['ECM']-score['alveolar']
 existing=pd.read_csv(ART/f'{acc}_scores.csv').set_index('sample_id').loc[sample_ids]
 errors={p:float(np.max(np.abs(v-existing['abundance_'+p].to_numpy()))) for p,v in score.items()}
 assert max(errors.values())<1e-10,errors
 result={'at':now(),'accession':acc,'max_absolute_score_errors':errors,'raw_source_streamed':True,'same_frozen_analysis_review':True,'new_trial':False}
 reported=json.loads((ART/f'{acc}_analysis.json').read_text())
 if acc=='GSE199949':
  m=pd.read_csv(DATA/f'{acc}_samples_frozen.csv').set_index('sample_id').loc[sample_ids]
  m['review_balance']=score['balance'];m=m[m.eligible_adult & m.diagnosis.eq('IPF')]
  pairs=[]
  for donor,g in m.groupby('donor_id'):
   assert len(g)==2
   delta=float(abs(g.review_balance.iloc[0]-g.review_balance.iloc[1]));pairs.append({'donor_id':donor,'abs_difference':delta,'event':delta>=1})
  k=sum(p['event'] for p in pairs);n=len(pairs)
  # Invert binomial tails numerically rather than using beta distribution formula.
  low=brentq(lambda p:binom.sf(k-1,n,p)-.025,0,1) if k else 0.
  high=brentq(lambda p:binom.cdf(k,n,p)-.025,0,1) if k<n else 1.
  primary=reported['primary_test'];assert k==primary['k'] and n==primary['n']
  assert np.allclose([low,high],primary['ci95'],atol=1e-10)
  result['primary_independent_reconstruction']={'pairs':pairs,'k':k,'n':n,'ci95_binomial_tail_inversion':[low,high],'matches':True}
 donors=pd.read_csv(ART/f'{acc}_donor_scores.csv')
 dd=donors[~donors.sex_conflict & donors.age.notna()].copy()
 x=np.column_stack([np.ones(len(dd)),dd.diagnosis.eq('IPF').astype(float),(dd.age-dd.age.mean())/10,dd.sex.str.lower().isin(['male','m']).astype(float)])
 checks={}
 for p in plan['programs']|{'balance':[]}:
  key='abundance_'+p
  fit=sm.OLS(dd[key],x).fit(cov_type='HC3',use_t=True)
  old=reported['by_score'][key]['disease_effect']['age_sex_adjusted']
  if old['status']=='estimated':
   error=float(abs(fit.params.iloc[1]-old['disease_coefficient']));cierror=float(np.max(np.abs(fit.conf_int().iloc[1].to_numpy()-old['ci95'])))
   assert error<1e-8 and cierror<1e-8
   checks[key]={'coefficient_abs_error':error,'HC3_t_interval_abs_error':cierror}
 result['statsmodels_HC3_crosscheck']=checks
 if acc=='GSE150910':
  extra=pd.get_dummies(dd[['sample type','institution']],drop_first=True,dtype=float)
  fullx=np.column_stack([x,extra.to_numpy()]);fullchecks={}
  for p in plan['programs']|{'balance':[]}:
   key='abundance_'+p;old=reported['by_score'][key]['disease_effect']['age_sex_sampling_institution_adjusted']
   if old['status']=='estimated':
    fit=sm.OLS(dd[key],fullx).fit(cov_type='HC3',use_t=True)
    error=float(abs(fit.params.iloc[1]-old['disease_coefficient']));cierror=float(np.max(np.abs(fit.conf_int().iloc[1].to_numpy()-old['ci95'])))
    assert error<1e-8 and cierror<1e-8
    fullchecks[key]={'coefficient_abs_error':error,'HC3_t_interval_abs_error':cierror}
   else:
    leverage=np.diag(fullx@np.linalg.pinv(fullx))
    fullchecks[key]={'reported_status':old['status'],'independent_rank':int(np.linalg.matrix_rank(fullx)),'columns':fullx.shape[1],'maximum_hat_diagonal':float(leverage.max()),'new_estimate_not_run':True}
  result['full_context_model_review']=fullchecks
 atomic(ART/f'{acc}_independent_numeric_review.json',result)
 print(json.dumps(result))

if __name__=='__main__':
 for acc in sys.argv[1:]:reconstruct(acc)
