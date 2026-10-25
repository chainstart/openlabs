"""Predeclared secondary calibration, using already frozen predictions and bootstrap draws."""
from common import *
import numpy as np
import pandas as pd

def main():
    frozen=json.loads((ART/'models-frozen.json').read_text())
    target=pd.read_csv(ART/'sealed/external-target.csv.gz')
    boot=np.load(ART/'bootstrap-results.npz')
    cellmap={x:i for i,x in enumerate(sorted(target.depmap_id.unique()))}
    names=frozen['learned'];B=len(boot['drug_weights']);D=len(frozen['scores'])
    bs_bias=np.zeros((B,D,len(names)));bs_brier=np.zeros_like(bs_bias)
    rows=[]
    for di,entry in enumerate(frozen['scores']):
        z=np.load(entry['path'],allow_pickle=False);n=len(z['models']);i=z['i'];j=z['j']
        t=target[target.structure_key==entry['structure_key']].set_index('depmap_id').loc[z['models']]
        a=z['raw_direction'];values=t.target_auc.to_numpy();b=values[i]-values[j]
        e=np.where((a==0)|(b==0),.5,((a>0)!=(b>0)).astype(float))
        W=boot['cell_weights'][:,[cellmap[c] for c in z['models']]]
        denom=(W.sum(axis=1)**2-(W**2).sum(axis=1))/2
        assert (denom>0).all()
        for mi,name in enumerate(names):
            risk=z['risks'][:,mi]
            bias=e-risk
            expected_brier=risk*risk-2*risk*e+e
            for vals,dest in [(bias,bs_bias),(expected_brier,bs_brier)]:
                mat=np.zeros((n,n));mat[i,j]=vals
                dest[:,di,mi]=np.sum((W@mat)*W,axis=1)/denom
            rows.append({'structure_key':entry['structure_key'],'method':name,'observed_error':float(e.mean()),
                         'predicted_error':float(risk.mean()),'underprediction':float(bias.mean()),'expected_binary_brier':float(expected_brier.mean())})
        print('Calibration review',di+1,D,flush=True)
    table=pd.DataFrame(rows);table.to_csv(ART/'calibration-summary-by-drug.csv',index=False)
    bias_boot=np.einsum('bd,bdm->bm',boot['drug_weights'],bs_bias)/D
    brier_boot=np.einsum('bd,bdm->bm',boot['drug_weights'],bs_brier)/D
    out={}
    for mi,name in enumerate(names):
        g=table[table.method==name]
        out[name]={'predicted_error':float(g.predicted_error.mean()),'observed_error':float(g.observed_error.mean()),
                   'underprediction':float(g.underprediction.mean()),'underprediction_two_way_ci95':np.quantile(bias_boot[:,mi],[.025,.975]).tolist(),
                   'expected_binary_brier':float(g.expected_binary_brier.mean()),'brier_two_way_ci95':np.quantile(brier_boot[:,mi],[.025,.975]).tolist()}
    k=names.index('hgb_full');c=names.index('isotonic_gap')
    comparison={'brier_reduction_full_vs_isotonic':float(out['isotonic_gap']['expected_binary_brier']-out['hgb_full']['expected_binary_brier']),
                'two_way_ci95':np.quantile(brier_boot[:,c]-brier_boot[:,k],[.025,.975]).tolist()}
    bins=pd.read_csv(ART/'external-calibration-by-drug.csv')
    binsummary=bins.groupby(['method','bin']).agg(n_drugs=('structure_key','nunique'),n_comparisons=('n_comparisons','sum'),predicted=('predicted','mean'),observed=('observed','mean')).reset_index()
    binsummary.to_csv(ART/'calibration-fixed-bins.csv',index=False)
    result={'at':now(),'status':'predeclared_secondary_only','configurations_unchanged':12,'models':out,'full_vs_gap_calibration':comparison,
            'fixed_bins':'calibration-fixed-bins.csv; equal-drug within-bin summaries, descriptive, no independent-comparison claim',
            'brier_definition':'Expected squared binary loss, with random 0/1 convention for ties: p^2-2*p*y+y. Also retain original squared error to tie-coded outcomes in confirmation-results. The additive tie variance is identical across learned models.',
            'interpretation':'Positive underprediction means technical-repeat-trained probabilities are optimistic for observed CTRP disagreement. This is a bounded screen-transfer calibration result, not causal attribution or clinical error probability.',
            'bootstrap':'Same1000 predeclared chemical x cell draws; fixed fitted models and observed source panel',
            'code_sha256':sha256_file(__file__)}
    write(ART/'calibration-results.json',result);write(DATA/'calibration-results.json',result)
    np.savez_compressed(ART/'calibration-bootstrap.npz',methods=np.array(names),bias=bias_boot,brier=brier_boot)
    ledger=json.loads((DATA/'all-trials-ledger.json').read_text())
    ledger['current_campaign']['trials'].append({'at':now(),'type':'predeclared_secondary_calibration','model_configurations_unchanged':12,'new_confirmation':False,'new_target_calibration_fit':False})
    write(DATA/'all-trials-ledger.json',ledger)
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
