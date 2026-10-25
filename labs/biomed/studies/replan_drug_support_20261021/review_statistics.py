"""Independent result arithmetic, all selectors and direct pair-weight bootstrap review."""
from common import *
import numpy as np
import pandas as pd
import statistics

def wrong(a,b):
    out=((a>0)!=(b>0)).astype(float)
    out[(a==0)|(b==0)]=.5
    return out

def percentile(values,q):
    ordered=sorted(map(float,values));position=(len(ordered)-1)*q
    k=int(position);f=position-k
    return ordered[k] if k==len(ordered)-1 else ordered[k]*(1-f)+ordered[k+1]*f

def main():
    frozen=json.loads((ART/'models-frozen.json').read_text())
    result=json.loads((ART/'confirmation-results.json').read_text())
    original=pd.read_csv(ART/'external-by-drug.csv').set_index(['structure_key','method'])
    target=pd.read_csv(ART/'sealed/external-target.csv.gz')
    source=pd.read_csv(ART/'external-source-features.csv.gz')
    methods=frozen['methods'];boot=np.load(ART/'bootstrap-results.npz')
    cells=sorted(target.depmap_id.unique());cell_index={v:i for i,v in enumerate(cells)}
    selection_records=json.loads((ART/'preopening-selection-hashes.json').read_text())
    selection_hash={(r['structure_key'],r['method'],r['coverage']):r['index_sha256'] for r in selection_records}
    max_error=0.;max_direction_difference=0.;records=[]
    # First50 fixed bootstrap draws; direct per-comparison weights rather than matrices.
    direct=np.empty((50,len(frozen['scores']),2))
    for di,item in enumerate(frozen['scores']):
        key=item['structure_key'];z=np.load(item['path'],allow_pickle=False)
        ids=z['models'];i=z['i'];j=z['j'];tie=z['tie']
        t=target[target.structure_key==key].set_index('depmap_id').loc[ids]
        s=source[source.structure_key==key].set_index('depmap_id').loc[ids]
        assert t.index.tolist()==s.index.tolist()==ids.tolist()
        y=t.target_auc.to_numpy();d=y[i]-y[j]
        for name,col in [('raw','raw_auc'),('fit','fit_auc')]:
            pred=s[col].to_numpy();max_direction_difference=max(max_direction_difference,float(np.max(abs(pred[i]-pred[j]-z[name+'_direction']))))
        for mi,name in enumerate(methods):
            direction=z['fit_direction' if name=='gap_fit' else 'mean_direction' if name=='additive_mean' else 'raw_direction']
            error=wrong(direction,d)
            # Independent pandas multi-column ordering instead of original np.lexsort.
            order=pd.DataFrame({'score':z['scores'][:,mi],'tie':tie}).sort_values(['score','tie'],ascending=[False,True],na_position='last').index.to_numpy()
            expected=original.loc[(key,name)]
            for coverage in [.25,.5,.75]:
                ix=order[:int(len(i)*coverage)]
                h=hashlib.sha256(ix.astype('<i8').tobytes()).hexdigest()
                assert h==selection_hash[(key,name,coverage)],(key,name,coverage)
                estimate=float(sum(error[ix])/len(ix))
                max_error=max(max_error,abs(estimate-expected['error_'+str(coverage)]))
                records.append({'structure_key':key,'method':name,'coverage':coverage,'error':estimate})
                if coverage==.5 and name in ['gap_raw','hgb_full']:
                    mi2=['gap_raw','hgb_full'].index(name)
                    global_i=np.array([cell_index[ids[k]] for k in i[ix]])
                    global_j=np.array([cell_index[ids[k]] for k in j[ix]])
                    for b in range(50):
                        weights=boot['cell_weights'][b,global_i]*boot['cell_weights'][b,global_j]
                        direct[b,di,mi2]=float(np.dot(weights,error[ix])/weights.sum())
            max_error=max(max_error,abs(float(sum(error)/len(error))-expected.all_pair_error))
        print('Reviewed ranks',di+1,len(frozen['scores']),flush=True)
    assert max_error<1e-12 and max_direction_difference<1e-12
    D=len(frozen['scores']);direct_macro=np.empty((50,2))
    for b in range(50):
        for m in [0,1]:
            direct_macro[b,m]=sum(boot['drug_weights'][b,d]*direct[b,d,m] for d in range(D))/D
    recorded_macro=boot['two_way'][:50][:,[methods.index('gap_raw'),methods.index('hgb_full')]]
    bootstrap_error=float(np.max(abs(direct_macro-recorded_macro)));assert bootstrap_error<1e-12
    macro_checks={}
    table=pd.DataFrame(records)
    for mi,name in enumerate(methods):
        v=table[(table.method==name)&(table.coverage==.5)].error.tolist()
        p=statistics.fmean(v);ci=[percentile(boot['two_way'][:,mi],q) for q in [.025,.975]]
        assert abs(p-result['all_baselines'][name]['error_at_50pct'])<1e-12
        assert np.max(abs(np.array(ci)-result['all_baselines'][name]['two_way_ci95']))<1e-12
        macro_checks[name]={'point':p,'ci95':ci}
    delta=boot['two_way'][:,methods.index('gap_raw')]-boot['two_way'][:,methods.index('hgb_full')]
    ci=[percentile(delta,q) for q in [.025,.975]]
    assert np.max(abs(np.array(ci)-result['primary']['two_way_ci95']))<1e-12
    write(ART/'independent-statistical-review.json',{'at':now(),'all_passed':True,'all_drugs':D,'all_methods':len(methods),
          'all_coverages':[.25,.5,.75],'source_selection_hashes_all_unchanged':True,
          'max_per_drug_metric_error':max_error,'max_source_direction_difference':max_direction_difference,
          'direct_pair_weight_bootstrap_draws':50,'max_bootstrap_error':bootstrap_error,'percentile_interpolation':'independent sorted linear interpolation',
          'macros':macro_checks,'primary_ci95':ci,'code_sha256':sha256_file(__file__),
          'independent_implementation_not_new_confirmation':True,'same_research_agent_not_external_reviewer':True})
    print('All independent statistical checks passed',flush=True)

if __name__=='__main__':main()
