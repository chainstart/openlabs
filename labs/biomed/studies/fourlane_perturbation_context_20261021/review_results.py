"""Reconstruct saved losses; never fit or reopen confirmation data."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from scipy.stats import t
from intake import ART, DATA, atomic, now

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while b:=f.read(1024**2):h.update(b)
    return h.hexdigest()

def review(prefix):
    metrics=pd.read_csv(ART/(prefix+'_row_metrics.csv'))
    pred=np.load(ART/(prefix+'_predictions.npz'))
    original=json.loads((ART/(prefix+'_results.json')).read_text())
    observed=pred['observed'];ids=pred['sample_ids'];baseline=[];checks={}
    for model in [k for k in pred.files if k.startswith('M')]:
        yhat=pred[model]
        if not np.isfinite(yhat).all():raise ValueError('nonfinite saved predictions')
        loss=np.mean(np.square(observed-yhat),axis=1)
        rows=metrics[metrics.model==model].set_index('sample_id').loc[ids]
        difference=float(np.max(np.abs(loss-rows.mse.to_numpy())))
        if difference>1e-10:raise ValueError('reconstruction mismatch '+model)
        reconstructed=pd.DataFrame({'donor_id':rows.donor_id.to_numpy(),'loss':loss}).groupby('donor_id').loss.mean()
        vals=reconstructed.to_numpy();n=len(vals);mean=vals.mean();half=t.ppf(.975,n-1)*vals.std(ddof=1)/np.sqrt(n)
        if abs(mean-original['metrics'][model]['mean_donor_mse'])>1e-10:raise ValueError('donor aggregation mismatch')
        baseline.append({'model':model,'donor_mse_mean':float(mean),'donor_t95_lower':float(mean-half),'donor_t95_upper':float(mean+half),'n_donors':n})
        checks[model]=difference
    pd.DataFrame(baseline).to_csv(ART/(prefix+'_all_baseline_intervals.csv'),index=False)
    metrics.groupby(['model','donor_id','culture_condition']).mse.agg(['mean','count']).to_csv(ART/(prefix+'_condition_metrics.csv'))
    quality=metrics[metrics.model=='M5_shrunk_potency_ratio']
    report={'at_utc':now(),'scope':'independent arithmetic reconstruction of already-exposed saved predictions; not a new confirmation or model fit','prefix':prefix,'checked_rows':len(ids),'features':observed.shape[1],'largest_absolute_metric_difference':max(checks.values()),'model_checks':checks,'source_q_floor_rows':int(quality.source_q_floor.sum()),'raw_ratio_capped_rows':int(quality.raw_ratio_capped.sum()),'q_zero_rows':int(quality.q.eq(0).sum()),'q_range':[float(quality.q.min()),float(quality.q.max())],'q_shrunk_range':[float(quality.q_shrunk.min()),float(quality.q_shrunk.max())],'files':{str(p):sha(p) for p in [ART/(prefix+'_predictions.npz'),ART/(prefix+'_row_metrics.csv'),ART/(prefix+'_results.json')]}}
    atomic(DATA/(prefix+'_reconstruction.json'),report)
    print(json.dumps(report,indent=2))
    return report

def split_audit():
    dev=pd.read_csv(DATA/'screen_development_rows.csv',index_col=0)
    held=pd.read_csv(DATA/'screen_confirmation_rows.csv',index_col=0)
    primary=held[held.guide_partition.eq(2)]
    check={'at_utc':now(),'independent_unit':'donor','development_donors':sorted(dev.donor_id.unique()),'primary_confirmation_donors':sorted(primary.donor_id.unique()),'donor_overlap':sorted(set(dev.donor_id)&set(primary.donor_id)),'guide_overlap':sorted(set(dev.guide_id)&set(primary.guide_id)),'primary_sample_overlap':sorted(set(dev.index)&set(primary.index)),'rows':{'development':len(dev),'confirmation_primary':len(primary),'confirmation_residual_only':len(held)-len(primary)},'study_overlap':['GSE314342'],'protocol_three_way_donor_split_valid':False,'reason':'only two development and two held donors; no separate independent validation donor; crossed guide1/guide2 replication differs from three-way protocol','guide1_held_responses_used_for_training_or_primary':False}
    if check['donor_overlap'] or check['guide_overlap'] or check['primary_sample_overlap']:raise ValueError('screen isolation failed')
    check['primary_donor_and_guide_isolation_valid']=True
    atomic(DATA/'screen_split_audit.json',check)
    return check

if __name__=='__main__':
    for prefix in sys.argv[1:]:review(prefix)
    if 'screen_confirmation' in sys.argv[1:]:split_audit()
