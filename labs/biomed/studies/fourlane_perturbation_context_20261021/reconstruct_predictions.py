"""Independent arithmetic reconstruction from frozen parameters, without fitting.

This intentionally does not import calibration.py or call its prediction code.
The original confirmation files are read-only; the audit is not new evidence.
"""
import json
import sys
import numpy as np
import pandas as pd
from intake import ART, DATA, atomic, now

def suppressions(frame,prior):
    count=frame.target_count.to_numpy()+0.5;control=frame.control_target_count.to_numpy()+0.5
    relative=(count/(frame.library_size.to_numpy()+1))/(control/(frame.control_library_size.to_numpy()+1))
    logratio=np.log(count/(frame.library_size.to_numpy()+1))-np.log(control/(frame.control_library_size.to_numpy()+1))
    variance=1/count+1/control
    shrunk=prior['mu']+(prior['tau2']/(prior['tau2']+variance))*(logratio-prior['mu'])
    return np.clip(1-relative,0,1),np.clip(1-np.exp(shrunk),0,1)

def reconstruct(layer):
    prefix=layer+'_confirmation'
    source=pd.read_csv(ART/(layer+'_development_samples.csv'))
    source_y=np.load(ART/(layer+'_development_effects.npz'))['Y']
    held=pd.read_csv(ART/(layer+'_confirmation_samples.csv'))
    model=json.loads((DATA/(layer+'_final_model_frozen.json')).read_text())
    saved=np.load(ART/(prefix+'_predictions.npz'))
    held=held.set_index('sample_id').loc[saved['sample_ids']].reset_index()
    q,qs=suppressions(source,model['prior']);hq,hqs=suppressions(held,model['prior'])
    source=source.assign(q=q,qs=qs)
    def aggregate(target,condition=None):
        mask=source.target.eq(target)
        if condition is not None:mask &= source.culture_condition.eq(condition)
        idx=np.flatnonzero(mask)
        groups=[idx[source.iloc[idx].donor_id.to_numpy()==d] for d in sorted(source.iloc[idx].donor_id.unique())]
        if not groups:raise ValueError('no source')
        response=np.mean([source_y[ii].mean(axis=0) for ii in groups],axis=0)
        stat={key:float(np.mean([source.iloc[ii][key].mean() for ii in groups])) for key in ['q','qs','library_size','n_cells']}
        return response,stat
    failures=[];max_errors={key:0. for key in saved.files if key.startswith('M')}
    # One saved prediction array at a time bounds memory below the service cap.
    for key in max_errors:
        existing=saved[key]
        for i,row in held.iterrows():
            x,s=aggregate(row.target,row.culture_condition)
            raw=min(max(float(hq[i])/max(s['q'],.1),0),4)
            shr=min(max(float(hqs[i])/max(s['qs'],.1),0),4)
            if key=='M0_zero':actual=np.zeros_like(x)
            elif key=='M1_direct':actual=x
            elif key=='M2_linear':actual=model['alpha']*x
            elif key=='M3_condition_linear':actual=model['condition_alpha'][row.culture_condition]*x
            elif key=='M4_potency_ratio':actual=raw*x
            elif key=='M5_shrunk_potency_ratio':actual=shr*x
            elif key=='M6_linear_potency':actual=model['alpha_q']*shr*x
            elif key=='M7_depth_cells':
                cov=[1,np.log(max(row.library_size,1)/max(s['library_size'],1))]
                if model['has_cells']:cov.append(np.log(max(row.n_cells,1)/max(s['n_cells'],1)))
                actual=np.clip(np.dot(model['depth_coefficients'],cov),0,4)*x
            elif key=='M8_shared_context':actual=aggregate(row.target)[0]
            elif key=='M9_potency_shared':
                shared,ss=aggregate(row.target);actual=min(max(float(hq[i])/max(ss['q'],.1),0),4)*shared
            elif key=='M10_sqrt_potency':actual=np.sqrt(raw)*x
            elif key=='M11_squared_potency':actual=min(raw**2,4)*x
            else:raise ValueError('unregistered model '+key)
            delta=float(np.max(np.abs(actual-existing[i])))
            max_errors[key]=max(max_errors[key],delta)
            if delta>1e-10:failures.append({'model':key,'sample_id':row.sample_id,'max_abs_error':delta})
    report={'at_utc':now(),'layer':layer,'scope':'deterministic reconstruction of previously evaluated confirmation using frozen parameters; no refitting, reselection or new independent confirmation','calibration_module_imported':False,'n_models':len(max_errors),'n_rows':len(held),'max_absolute_prediction_errors':max_errors,'valid':not failures,'failures':failures}
    atomic(DATA/(layer+'_prediction_reconstruction.json'),report)
    print(json.dumps(report,indent=2))
    if failures:raise ValueError('prediction reconstruction mismatch')

if __name__=='__main__':
    for layer in sys.argv[1:]:reconstruct(layer)
