"""Cross-check already registered rank baselines and secondary slopes.

Uses source rows and pandas rank instead of the primary scipy rank path.
No new scientific endpoint, fitted model choice or holdout selection.
"""
from common import *
import csv,gzip,re
import pandas as pd,numpy as np
from scipy.stats import linregress

plan=json.loads((DATA/'plan_frozen_v1.json').read_text())
ref=json.loads((DATA/'annotation_readonly_reference.json').read_text())
ann=pd.read_csv(ref['path'],sep='\t');ann=ann[ann.ensembl.notna()&ann.GeneName.notna()&ann.ExonLength.gt(0)]
ann=ann[~ann.GeneName.duplicated(keep=False)].set_index('ensembl')
univ=pd.read_csv(DATA/'gene_universe_frozen.csv');pos={en:i for i,en in enumerate(univ.ensembl)}
files={'GSE184316':'GSE184316_fHP_Txome_FPKM_RNAseq.csv.gz','GSE199949':'GSE199949_raw.counts.txt.gz','GSE150910':'GSE150910_gene-level_count_file.csv.gz'}
review={}
for acc,filename in files.items():
 fmt=json.loads((DATA/f'{acc}_format_audit.json').read_text());ids=list(fmt['sample_map']);cols=[fmt['header'].index(fmt['sample_map'][s]) for s in ids]
 mp=pd.read_csv(DATA/f'{acc}_gene_mapping.csv').set_index('source_id').ensembl.to_dict()
 matrix=np.zeros((len(univ),len(ids)))
 with gzip.open(ART/'payload'/filename,'rt') as f:
  reader=csv.reader(f,delimiter=fmt['delimiter']);next(reader)
  for row in reader:
   if not row:continue
   en=mp.get(row[0])
   if en not in pos:continue
   v=np.array([float(row[c]) for c in cols])
   if acc!='GSE184316':v/=float(ann.loc[en,'ExonLength'])
   matrix[pos[en]]+=v
 # Any positive sample-wide normalization factor preserves within-sample ranks.
 ranks=pd.DataFrame(matrix,index=univ.symbol,columns=ids).rank(axis=0,method='min')
 calculated={}
 for p,genes in plan['programs'].items():
  n=len(ranks);k=len(genes);lo=(1+k)/2;hi=(n-k+1+n)/2
  calculated['singscore_'+p]=(ranks.loc[genes].mean(axis=0)-lo)/(hi-lo)-.5
 calculated['singscore_bidirectional']=calculated['singscore_ECM']-calculated['singscore_alveolar']
 existing=pd.read_csv(ART/f'{acc}_scores.csv').set_index('sample_id').loc[ids]
 errors={name:float(np.max(np.abs(v.to_numpy()-existing[name].to_numpy()))) for name,v in calculated.items()}
 assert max(errors.values())<1e-12,errors
 review[acc]={'rank_score_max_absolute_errors':errors,'same_frozen_baseline':True,'n_common_genes':len(ranks),'score_ranges':{name:{'min':float(existing[name].min()),'max':float(existing[name].max())} for name in calculated}}
 if acc=='GSE184316':
  observed=json.loads((ART/f'{acc}_analysis.json').read_text());slope_errors={}
  for name,e in observed['by_score'].items():
   per={v['donor_id']:v['slope'] for v in e['within_donor_surface_density_slope']['per_donor']};errs=[]
   for donor,g in existing[existing.eligible_adult&existing.diagnosis.eq('IPF')].groupby('donor_id'):
    value=linregress(g['surface density'].to_numpy()/0.001,g[name].to_numpy()).slope
    errs.append(abs(value-per[donor]))
   slope_errors[name]=float(max(errs));assert slope_errors[name]<1e-12
  review[acc]['linregress_secondary_slope_max_absolute_errors']=slope_errors
record=dict(at=now(),review=review,code_sha256=sha(Path(__file__)),new_scientific_configuration=False,all_pass=True,scope='Independent implementation review of exactly the frozen published baseline and already estimated secondary slopes; no threshold/model changes')
atomic(ART/'rank_and_secondary_numeric_review.json',record)
print(json.dumps(record))
