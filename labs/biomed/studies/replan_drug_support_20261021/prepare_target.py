"""Process frozen CTRP target into sealed artifacts; do not compare with source."""
from common import *
from prepare_source import check_freeze
from curve_math import empirical_auc
import numpy as np
import pandas as pd

def main():
    check_freeze()
    assert not (ART/'confirmation-opened.json').exists()
    assert not (ART/'target-preparation-complete.json').exists()
    p=ART/'intake/CTRP_replicates.csv'
    assert sha256_file(p)==json.loads(p.with_name(p.name+'.manifest.json').read_text())['sha256']
    write(ART/'target-preprocessing-exposure.json',{'at':now(),'stage':'frozen_preprocessing_only','note':'First numeric CTRP response parsing. No source-target errors, correlations, or model comparisons inspected; source features/models separate. Labels no longer byte-unread, but effect evaluation remains unopened.','plan_sha256':sha256_file(DATA/'plan-frozen.json'),'code_sha256':sha256_file(__file__)})
    samples=pd.read_csv(DATA/'metadata-qualified-pairs.csv')
    samples=samples[samples.source_eligible].copy()
    ids=samples[['drug','cell_line','structure_key','depmap_id']]
    assert not ids.duplicated(['drug','cell_line']).any()
    blocks=[];nread=0
    for c in pd.read_csv(p,chunksize=100000):
        nread+=len(c)
        hit=c.merge(ids,on=['drug','cell_line'],validate='many_to_one')
        if len(hit):blocks.append(hit)
    raw=pd.concat(blocks,ignore_index=True)
    raw['finite']=np.isfinite(raw.dose)&np.isfinite(raw.response)
    missing=int((~raw.finite).sum())
    raw=raw[raw.finite]
    grouped=raw.groupby(['structure_key','depmap_id','dose']).response.median().reset_index()
    lookup={(k,m):g.sort_values('dose') for (k,m),g in grouped.groupby(['structure_key','depmap_id'])}
    output=[];exclusions=[];curves=[]
    for r in samples.itertuples(index=False):
        key=(r.structure_key,r.depmap_id);g=lookup.get(key)
        base={'drug':r.drug,'structure_key':r.structure_key,'cell_line':r.cell_line,'depmap_id':r.depmap_id,'common_lo':r.common_lo,'common_hi':r.common_hi}
        if g is None:
            exclusions.append(dict(base,reason='no finite target measurements'));continue
        x=g.dose.to_numpy();y=g.response.to_numpy()
        within=(x>=r.common_lo)&(x<=r.common_hi)
        if len(x)<4 or within.sum()<4 or x.min()>r.common_lo or x.max()<r.common_hi:
            exclusions.append(dict(base,reason='target dose coverage or distinct dose count',n_doses=len(x),n_inside=int(within.sum()),actual_lo=float(x.min()),actual_hi=float(x.max())));continue
        auc=empirical_auc(10.**x,y,r.common_lo,r.common_hi)
        unclip=empirical_auc(10.**x,y,r.common_lo,r.common_hi,clip=False)
        output.append(dict(base,target_auc=auc,target_unclipped_auc=unclip,n_distinct_doses=len(x)))
        curves.append(dict(base,log_doses=x.tolist(),median_response=y.tolist()))
    out=pd.DataFrame(output)
    counts=out.groupby('structure_key').size();keep=set(counts[counts>=20].index)
    excluded_drugs=set(out.structure_key)-keep
    for key in excluded_drugs:exclusions.append({'structure_key':key,'reason':'fewer than20 complete matched target cells','n_cells':int(counts[key])})
    out=out[out.structure_key.isin(keep)]
    (ART/'sealed').mkdir(exist_ok=True)
    out.to_csv(ART/'sealed/external-target.csv.gz',index=False)
    write(ART/'sealed/external-target-curves.json',curves)
    write(ART/'target-exclusions.json',exclusions)
    out.drop(columns=['target_auc','target_unclipped_auc']).to_csv(DATA/'external-eligible-identifiers.csv',index=False)
    result={'at':now(),'input_rows':nread,'selected_finite_measurement_rows':len(raw),'selected_nonfinite_rows':missing,
            'eligible_pairs':len(out),'eligible_structures':out.structure_key.nunique(),'eligible_models':out.depmap_id.nunique(),
            'excluded_drugs':sorted(excluded_drugs),'exclusion_records':len(exclusions),
            'effects_evaluated':False,'selection_basis':'frozen identities, finite values, dose coverage, >=20 cells; no fit or response strength filters',
            'hashes':{str(f):sha256_file(f) for f in [ART/'sealed/external-target.csv.gz',ART/'sealed/external-target-curves.json',DATA/'external-eligible-identifiers.csv',ART/'target-exclusions.json']}}
    write(ART/'target-preparation-complete.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
