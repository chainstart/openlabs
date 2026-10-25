"""Post-confirmation dependency audit; never replaces the preregistered analysis."""
from common import *
from pair_math import selected
from evaluate import weighted_pair_mean
import numpy as np
import pandas as pd

def main():
    write(ART/'dependence-sensitivity-registration.json',{'at':now(),'timing':'post-confirmation supplementary sensitivity, not preregistered primary',
          'reason':'Review of26 shared source compound plates and20 source cell pools; audit whether chemical x cell interval omits important known clustering.',
          'comparisons':['source plate x cell','chemical x source pool','source plate x source pool'],'new_models':False,'new_selection':False,'no_replacement_of_primary':True,
          'remaining_limit':'CTRP author table lacks target plate IDs; these sensitivities cannot account for unknown target-plate dependence.'})
    frozen=json.loads((ART/'models-frozen.json').read_text());baseboot=np.load(ART/'bootstrap-results.npz')
    target=pd.read_csv(ART/'sealed/external-target.csv.gz')
    cellids=sorted(target.depmap_id.unique());cellmap={c:i for i,c in enumerate(cellids)}
    old=ROOT/'openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/drug_support'
    path=old/'intake/prism19-secondary-screen-pooling-info.csv'
    assert sha256_file(path)==json.loads(path.with_name(path.name+'.manifest.json').read_text())['sha256']
    pool=pd.read_csv(path)
    cp=pool[pool.screen_id.isin(['HTS002','MTS006'])&pool.depmap_id.isin(cellids)].groupby('depmap_id').pool_id.agg(lambda x:sorted(set(x)))
    assert set(cp.index)==set(cellids) and cp.map(len).eq(1).all()
    cell_pool={c:v[0] for c,v in cp.items()};pools=sorted(set(cell_pool.values()))
    plates=sorted(set(x['source_plate'] for x in frozen['scores']))
    assert all('|' not in p for p in plates)
    B=1000;D=len(frozen['scores']);rng=np.random.default_rng(20261021)
    platew=rng.multinomial(len(plates),np.full(len(plates),1/len(plates)),size=B).astype(float)
    poolw=rng.multinomial(len(pools),np.full(len(pools),1/len(pools)),size=B).astype(float)
    drugw=np.column_stack([platew[:,plates.index(e['source_plate'])] for e in frozen['scores']])
    cw=np.column_stack([poolw[:,pools.index(cell_pool[c])] for c in cellids])
    values=np.zeros((B,D,2))
    for di,entry in enumerate(frozen['scores']):
        z=np.load(entry['path'],allow_pickle=False);i=z['i'];j=z['j'];n=len(z['models'])
        t=target[target.structure_key==entry['structure_key']].set_index('depmap_id').loc[z['models']]
        y=t.target_auc.to_numpy();a=z['raw_direction'];b=y[i]-y[j]
        error=np.where((a==0)|(b==0),.5,((a>0)!=(b>0)).astype(float))
        W=cw[:,[cellmap[c] for c in z['models']]]
        for k,name in enumerate(['gap_raw','hgb_full']):
            ix=selected(z['scores'][:,frozen['methods'].index(name)],z['tie'],.5)
            values[:,di,k]=weighted_pair_mean(W,i[ix],j[ix],error[ix],n)
        print('Pool sensitivity',di+1,D,flush=True)
    # Main evaluator stored only marginal bootstrap results, so recompute the
    # plate x cell option with the original cell weights and identical pair sets.
    cell_values=np.zeros_like(values)
    for di,entry in enumerate(frozen['scores']):
        z=np.load(entry['path'],allow_pickle=False);i=z['i'];j=z['j'];n=len(z['models'])
        t=target[target.structure_key==entry['structure_key']].set_index('depmap_id').loc[z['models']]
        y=t.target_auc.to_numpy();a=z['raw_direction'];b=y[i]-y[j]
        error=np.where((a==0)|(b==0),.5,((a>0)!=(b>0)).astype(float))
        W=baseboot['cell_weights'][:,[cellmap[c] for c in z['models']]]
        for k,name in enumerate(['gap_raw','hgb_full']):
            ix=selected(z['scores'][:,frozen['methods'].index(name)],z['tie'],.5)
            cell_values[:,di,k]=weighted_pair_mean(W,i[ix],j[ix],error[ix],n)
    comparisons={}
    for name,dw,v in [('plate_cell',drugw,cell_values),('drug_pool',baseboot['drug_weights'],values),('plate_pool',drugw,values)]:
        estimate=np.einsum('bd,bdm->bm',dw,v)/dw.sum(axis=1)[:,None]
        delta=estimate[:,0]-estimate[:,1]
        comparisons[name]={'ci95':np.quantile(delta,[.025,.975]).tolist(),'bootstrap_mean':float(delta.mean()),'bootstrap_draws':B}
    write(ART/'dependence-sensitivity.json',{'at':now(),'timing':'post-confirmation secondary dependency audit','source_plates':len(plates),'source_pools':len(pools),
         'comparisons':comparisons,'primary_unchanged':True,'unresolved_target_plate_dependence':True,'code_sha256':sha256_file(__file__)})
    print(json.dumps(comparisons,indent=2),flush=True)

if __name__=='__main__':main()
