"""Frozen simple response-transfer models. No CUDA or test-time fitting."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t
from intake import ART, DATA, atomic, now

MODELS=['M0_zero','M1_direct','M2_linear','M3_condition_linear','M4_potency_ratio',
        'M5_shrunk_potency_ratio','M6_linear_potency','M7_depth_cells',
        'M8_shared_context','M9_potency_shared','M10_sqrt_potency','M11_squared_potency']

def potency(meta,prior=None):
    a=meta.target_count.to_numpy(float)+.5
    b=meta.control_target_count.to_numpy(float)+.5
    u=np.log(a/(meta.library_size.to_numpy(float)+1))-np.log(b/(meta.control_library_size.to_numpy(float)+1))
    v=1/a+1/b
    if prior is None:prior={'mu':float(u.mean()),'tau2':float(max(u.var(ddof=1)-v.mean(),.05))}
    w=prior['tau2']/(prior['tau2']+v)
    sh=prior['mu']+w*(u-prior['mu'])
    return np.clip(1-np.exp(u),0,1),np.clip(1-np.exp(sh),0,1),prior,u,v

def source_for(meta,Y,target,condition,exclude_donor=None,shared=False):
    mask=meta.target.eq(target).to_numpy()
    if not shared:mask &= meta.culture_condition.eq(condition).to_numpy()
    if exclude_donor is not None:mask &= ~meta.donor_id.eq(exclude_donor).to_numpy()
    ids=np.flatnonzero(mask)
    if len(ids)==0:return None
    # First average repeated measurements within biological donor, then donors.
    donor_groups=[ids[meta.iloc[ids].donor_id.to_numpy()==d] for d in sorted(meta.iloc[ids].donor_id.unique())]
    avg=lambda z:np.mean([np.mean(np.asarray(z)[ii],axis=0) for ii in donor_groups],axis=0)
    return {'Y':avg(Y),'q':float(avg(meta.q)),'qs':float(avg(meta.qs)),
            'library_size':float(avg(meta.library_size)),'n_cells':float(avg(meta.n_cells)),
            'source_donors':sorted(meta.iloc[ids].donor_id.unique())}

def ratio(q,s):return float(np.clip(q/max(s,.1),0,4))
def zfeatures(row,source,has_cells):
    z=[1.,np.log(max(float(row.library_size),1)/max(source['library_size'],1))]
    if has_cells:z.append(np.log(max(float(row.n_cells),1)/max(source['n_cells'],1)))
    return np.asarray(z)
def fit(meta,Y,has_cells=True):
    meta=meta.copy();q,qs,prior,_,_=potency(meta);meta['q']=q;meta['qs']=qs
    pairs=[]
    for i,row in meta.iterrows():
        s=source_for(meta,Y,row.target,row.culture_condition,row.donor_id)
        if s is None:continue
        x=s['Y'];y=Y[i];z=zfeatures(row,s,has_cells)
        pairs.append({'donor':row.donor_id,'condition':row.culture_condition,'xx':float(np.mean(x*x)),
                      'xy':float(np.mean(x*y)),'r':ratio(row.qs,s['qs']),'z':z})
    if not pairs:raise ValueError('No independent development donor pairs')
    nd={d:sum(p['donor']==d for p in pairs) for d in {p['donor'] for p in pairs}}
    weights=np.array([1/nd[p['donor']] for p in pairs]);weights/=weights.sum()
    xx=np.array([p['xx'] for p in pairs]);xy=np.array([p['xy'] for p in pairs]);r=np.array([p['r'] for p in pairs])
    alpha=float(np.clip(np.sum(weights*xy)/max(np.sum(weights*xx),1e-12),0,4))
    alpha_q=float(np.clip(np.sum(weights*r*xy)/max(np.sum(weights*r*r*xx),1e-12),0,4))
    cond={}
    for c in sorted(meta.culture_condition.unique()):
        mask=np.array([p['condition']==c for p in pairs]);w=weights*mask
        cond[c]=float(np.clip(np.sum(w*xy)/max(np.sum(w*xx),1e-12),0,4))
    Z=np.stack([p['z'] for p in pairs]);penalty=np.eye(Z.shape[1]);penalty[0,0]=0
    beta=np.linalg.solve(Z.T@((weights*xx)[:,None]*Z)+penalty,Z.T@(weights*xy))
    return {'prior':prior,'alpha':alpha,'alpha_q':alpha_q,'condition_alpha':cond,'depth_coefficients':beta.tolist(),'has_cells':has_cells,'calibration_pairs':len(pairs),'training_donors':sorted(meta.donor_id.unique()),'fitted_at_utc':now()}

def evaluate(source_meta,source_Y,meta,Y,model,out_prefix,screen=False):
    source_meta=source_meta.copy();meta=meta.copy()
    source_meta['q'],source_meta['qs'],_,_,_=potency(source_meta,model['prior'])
    meta['q'],meta['qs'],_,meta['u'],meta['v']=potency(meta,model['prior'])
    chosen=MODELS if screen else [x for x in MODELS if x not in ['M8_shared_context','M9_potency_shared']]
    preds={k:[] for k in chosen};records=[];included=[]
    for i,row in meta.iterrows():
        s=source_for(source_meta,source_Y,row.target,row.culture_condition)
        if s is None:
            records.append({'sample_id':row.sample_id,'target':row.target,'donor_id':row.donor_id,'excluded':'no development source for target/condition'})
            continue
        assert row.donor_id not in s['source_donors'], 'donor leakage in evaluation'
        r=ratio(row.q,s['q']);rs=ratio(row.qs,s['qs']);x=s['Y']
        amp={'M0_zero':0,'M1_direct':1,'M2_linear':model['alpha'],
             'M3_condition_linear':model['condition_alpha'][row.culture_condition],
             'M4_potency_ratio':r,'M5_shrunk_potency_ratio':rs,'M6_linear_potency':model['alpha_q']*rs,
             'M7_depth_cells':float(np.clip(np.dot(model['depth_coefficients'],zfeatures(row,s,model['has_cells'])),0,4)),
             'M10_sqrt_potency':np.sqrt(r),'M11_squared_potency':min(r*r,4)}
        pred={k:amp[k]*x for k in chosen if k in amp}
        if screen:
            shared=source_for(source_meta,source_Y,row.target,row.culture_condition,shared=True)
            pred['M8_shared_context']=shared['Y'];pred['M9_potency_shared']=ratio(row.q,shared['q'])*shared['Y']
        y=Y[i];included.append(i)
        for k in chosen:
            yh=pred[k];preds[k].append(yh)
            xc=yh-yh.mean();yc=y-y.mean();den=np.linalg.norm(xc)*np.linalg.norm(yc)
            records.append({'sample_id':row.sample_id,'target':row.target,'donor_id':row.donor_id,
                            'guide_id':row.guide_id,'culture_condition':row.culture_condition,'model':k,
                            'mse':float(np.mean((y-yh)**2)),'pearson':float(np.dot(xc,yc)/den) if den>0 else None,
                            'q':row.q,'q_shrunk':row.qs,'source_q':s['q'],'source_q_shrunk':s['qs'],
                            'q_ratio':r,'q_shrunk_ratio':rs,'raw_ratio_capped':bool(row.q/max(s['q'],.1)>=4),
                            'source_q_floor':bool(s['q']<.1),'n_cells':row.n_cells,'library_size':row.library_size})
    result=pd.DataFrame(records);result.to_csv(ART/(out_prefix+'_row_metrics.csv'),index=False)
    np.savez_compressed(ART/(out_prefix+'_predictions.npz'),**{k:np.stack(v) for k,v in preds.items()},observed=Y[included],sample_ids=meta.iloc[included].sample_id.to_numpy(str))
    donors=result[result.model.notna()].groupby(['model','donor_id'],observed=True).mse.mean().unstack(0)
    donors.to_csv(ART/(out_prefix+'_donor_metrics.csv'))
    metrics={k:{'mean_donor_mse':float(donors[k].mean()),'n_donors':len(donors),'donor_mse':donors[k].to_dict()} for k in chosen}
    contrasts={}
    for baseline in ['M0_zero','M1_direct','M2_linear','M3_condition_linear','M7_depth_cells']:
        dif=donors[baseline]-donors['M5_shrunk_potency_ratio'];rel=dif/donors[baseline]
        contrasts[baseline]={'absolute_gain':interval(dif),'relative_gain':interval(rel)}
    summary={'stage':'exploratory_pilot','metrics':metrics,'primary_M5_vs_M2':contrasts['M2_linear'],'M5_vs_baselines':contrasts,
             'n_rows':len(included),'n_targets':int(meta.iloc[included].target.nunique()),'n_features':Y.shape[1],
             'scope':'donor-based uncertainty; same-study, no causal interpretation','frozen_plan_sha256':hashlib.sha256((DATA/'frozen_plan_v1.json').read_bytes()).hexdigest()}
    atomic(ART/(out_prefix+'_results.json'),summary)
    return summary

def interval(values):
    v=np.asarray(values,float);n=len(v);mean=float(v.mean());sd=float(v.std(ddof=1)) if n>1 else None
    half=float(t.ppf(.975,n-1)*sd/np.sqrt(n)) if n>1 else None
    rng=np.random.default_rng(20261021);boot=np.mean(rng.choice(v,(2000,n),replace=True),axis=1)
    return {'estimate':mean,'donor_t95':[mean-half,mean+half] if half is not None else None,'donor_bootstrap95':np.quantile(boot,[.025,.975]).tolist(),'n_independent_donors':n,'donor_sd':sd,'donor_values':v.tolist()}
