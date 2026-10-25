"""Prespecified descriptive strata; no reselection, tuning or significance claims."""
from common import *
from pair_math import selected
import pandas as pd
import numpy as np

def main():
    dev=pd.read_csv(ART/'development-features.csv.gz');train=dev[dev.role=='train']
    assert len(train)==9292
    drugs=set(train.structure_key);cells=set(train.depmap_id)
    link=pd.read_csv(DATA/'cell-linkage.csv').set_index('depmap_id')
    old=ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/drug_support'
    p=old/'intake/prism19-secondary-screen-pooling-info.csv';assert sha256_file(p)==json.loads(p.with_name(p.name+'.manifest.json').read_text())['sha256']
    pools=pd.read_csv(p);pools=pools[pools.screen_id.isin(['HTS002','MTS006'])].groupby('depmap_id').pool_id.first()
    target=pd.read_csv(ART/'sealed/external-target.csv.gz');frozen=json.loads((ART/'models-frozen.json').read_text());rows=[]
    for e in frozen['scores']:
        z=np.load(e['path'],allow_pickle=False);ids=z['models'];i=z['i'];j=z['j']
        y=target[target.structure_key==e['structure_key']].set_index('depmap_id').loc[ids].target_auc.to_numpy();b=y[i]-y[j];a=z['raw_direction']
        err=np.where((a==0)|(b==0),.5,((a>0)!=(b>0)).astype(float))
        present=np.array([x in cells for x in ids]);tissue=link.loc[ids].primary_tissue.fillna('unknown').to_numpy();pool=pools.loc[ids].to_numpy()
        groups={'training_drug':np.repeat('present' if e['structure_key'] in drugs else 'absent',len(i)),
                'training_cells':np.where(present[i]&present[j],'both_present',np.where(present[i]|present[j],'one_present','neither_present')),
                'tissue':np.where(tissue[i]==tissue[j],tissue[i],'cross_tissue'),
                'source_pool':np.where(pool[i]==pool[j],pool[i],'cross_pool')}
        for method in ['gap_raw','hgb_full']:
            ix=selected(z['scores'][:,frozen['methods'].index(method)],z['tie'],.5)
            for dim,g in groups.items():
                for label in np.unique(g[ix]):
                    subset=ix[g[ix]==label];rows.append({'structure_key':e['structure_key'],'dimension':dim,'stratum':label,'method':method,'selected_pairs':len(subset),'error':float(err[subset].mean())})
    per=pd.DataFrame(rows);per.to_csv(ART/'descriptive-strata-by-drug.csv',index=False)
    summary=per.groupby(['dimension','stratum','method']).agg(error=('error','mean'),drugs=('structure_key','nunique'),selected_pairs=('selected_pairs','sum')).reset_index();summary.to_csv(ART/'descriptive-strata-summary.csv',index=False)
    write(ART/'descriptive-strata.json',{'at':now(),'timing':'predeclared descriptive secondary analysis completed in review','training_drugs':len(drugs),'training_cells':len(cells),'no_reselection':True,'within_stratum_coverage_not_fixed':True,'macro_weighting':'equal drugs among drugs with at least one retained pair in stratum; method counts may differ','no_new_confirmation_or_significance_claim':True,'code_sha256':sha256_file(__file__)})
    print(summary[summary.dimension.isin(['training_drug','training_cells'])].to_string(index=False))
if __name__=='__main__':main()
