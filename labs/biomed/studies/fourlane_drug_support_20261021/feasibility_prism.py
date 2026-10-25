"""Count eligible independent identities and measurement availability before freezing."""
from common import *
import csv
import numpy as np
import pandas as pd

meta=pd.read_csv(DATA/'paired-compound-metadata.csv')
tm=pd.read_csv(DATA/'treatment-metadata.csv')
cells=pd.read_csv(DATA/'cell-identity.csv')
fitpath=ART/'intake/prism19-secondary-screen-dose-response-curve-parameters.csv'
fits=pd.read_csv(fitpath,usecols=['broad_id','depmap_id','screen_id','row_name'])
mapping=tm[['broad_id','screen_id','structure_key']].dropna().drop_duplicates()
conf=mapping.groupby(['broad_id','screen_id']).structure_key.nunique()
assert conf.max()==1
fits=fits.merge(mapping,on=['broad_id','screen_id'],how='inner').merge(meta[['structure_key','source_screen']],on='structure_key')
fits=fits[(fits.screen_id==fits.source_screen)|(fits.screen_id=='MTS010')]
fits=fits[fits.depmap_id.isin(cells.depmap_id)]
fits['role']=np.where(fits.screen_id=='MTS010','target','source')
available=fits.groupby(['structure_key','depmap_id']).role.nunique()
paired=available[available==2].reset_index()[['structure_key','depmap_id']]
rows=[]
for file in ['secondary-screen-logfold-change.csv','secondary-screen-mfi.csv']:
    with (ART/'intake'/('prism19-'+file)).open() as f:
        reader=csv.reader(f);h=next(reader)
        ids=[next(iter(r)) for r in reader]
    rows.append({'file':file,'rows':len(ids),'header_columns':len(h)-1,'id_overlap_with_valid_cells':len(set(ids)&set(cells.row_name)),'columns_matching_metadata':len(set(h[1:])&set(tm.column_name))})
meta['common_min']=meta[['source_min','target_min']].max(axis=1)
meta['common_max']=meta[['source_max','target_max']].min(axis=1)
meta['common_log10_width']=np.log10(meta.common_max/meta.common_min)
def support_count(r,prefix):
    a=np.array(json.loads(r[prefix+'_doses']))
    return int(((a>=r.common_min*.99)&(a<=r.common_max*1.01)).sum())
meta['source_common_doses']=meta.apply(lambda r:support_count(r,'source'),axis=1)
meta['target_common_doses']=meta.apply(lambda r:support_count(r,'target'),axis=1)
meta['usable_common_support']=(meta.common_log10_width>=1.2)&(meta.source_common_doses>=4)&(meta.target_common_doses>=4)
meta.to_csv(DATA/'paired-compound-support.csv',index=False)
paired=paired[paired.structure_key.isin(meta[meta.usable_common_support].structure_key)]
paired.to_csv(DATA/'candidate-pairs-identifiers.csv',index=False)
n=int(meta.usable_common_support.sum())
precision=[{'n_test_drugs':int(n*.4),'assumed_between_drug_sd':sd,'normal_approx_95_halfwidth':1.96*sd/np.sqrt(int(n*.4)),'normal_approx_80pct_mde':2.8*sd/np.sqrt(int(n*.4))} for sd in [.03,.05,.1]]
result={'stage':'pre_outcome_feasibility','metadata_pair_count':len(paired),'drugs':paired.structure_key.nunique(),'cell_models':paired.depmap_id.nunique(),'common_support_drugs':n,'raw_schema':rows,'precision_scenarios':precision,'precision_caveat':'Planning approximations, not observed variance or promised power; two-way biological/model dependencies and shared assay plates can inflate uncertainty. Real precision reported after frozen evaluation.','target_label_exposure':'Only identifiers/schema parsed from response files. No fitted/observed target outcomes inspected. Raw CSV rows traversed as text solely to collect row identifier; not numerically parsed.'}
write(DATA/'feasibility-final.json',result)
print(json.dumps(result,indent=2))
