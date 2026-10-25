"""Fixed pair construction and source-only selectors; no target-dependent selection."""
import hashlib
import numpy as np
import pandas as pd

FEATURES=['raw_gap','fit_gap','mean_auc','min_auc','max_auc','pooled_se','mean_rep_sd','max_rep_sd','min_nrep','standardized_gap','repeat_agreement','mean_nrfe','max_nrfe','mean_rmse','max_rmse','mean_saturation_low','mean_saturation_high','mean_dynamic_range','difference_dynamic_range','fit_failed','common_lo','common_hi','support_width','source_log_min','source_log_max','source_n_doses']
DOSE_FEATURES=['common_lo','common_hi','support_width','source_log_min','source_log_max','source_n_doses']
METHODS=['gap_raw','gap_fit','additive_mean','repeat_agreement','standardized_gap','nrfe_curve','isotonic_gap','ridge_full','hgb_gap','hgb_full','hgb_dose']
LEARNED=['isotonic_gap','ridge_full','hgb_gap','hgb_full','hgb_dose']

def ranking_error(a,b):
    a=np.sign(np.asarray(a));b=np.sign(np.asarray(b))
    return np.where((a==0)|(b==0),.5,(a!=b).astype(float))

def selected(score,tie,coverage):
    n=int(np.floor(coverage*len(score)))
    score=np.nan_to_num(score,nan=-np.inf)
    return np.lexsort((tie,-score))[:n]

def make_pairs(frame,cap=None,seed=20261021):
    df=frame.sort_values('depmap_id').reset_index(drop=True)
    key=str(df.structure_key.iloc[0])
    i,j=np.triu_indices(len(df),k=1)
    if cap is not None and len(i)>cap:
        salted=int.from_bytes(hashlib.sha256((str(seed)+key).encode()).digest()[:8],'little')
        ix=np.sort(np.random.default_rng(salted).choice(len(i),cap,replace=False));i=i[ix];j=j[ix]
    get=lambda c:df[c].to_numpy(dtype=float)
    a=get('raw_auc');f=get('fit_auc');sd=get('rep_sd');n=get('nrep')
    raw_diff=a[i]-a[j];gap=abs(raw_diff);se=np.sqrt(sd[i]**2/n[i]+sd[j]**2/n[j])
    agree=np.zeros(len(i));denom=np.zeros(len(i))
    for r in [1,2,3]:
        ar=get('rep'+str(r)+'_auc')
        for s in [1,2,3]:
            br=get('rep'+str(s)+'_auc');ok=np.isfinite(ar[i])&np.isfinite(br[j])
            agree[ok]+=1-ranking_error(raw_diff[ok],ar[i][ok]-br[j][ok]);denom[ok]+=1
    agree=np.divide(agree,denom,out=np.full(len(i),.5),where=denom>0)
    x={'raw_gap':gap,'fit_gap':abs(f[i]-f[j]),'mean_auc':(a[i]+a[j])/2,'min_auc':np.minimum(a[i],a[j]),'max_auc':np.maximum(a[i],a[j]),'pooled_se':se,'mean_rep_sd':(sd[i]+sd[j])/2,'max_rep_sd':np.maximum(sd[i],sd[j]),'min_nrep':np.minimum(n[i],n[j]),'standardized_gap':gap/np.sqrt(se**2+.02**2),'repeat_agreement':agree}
    for original,prefix in [('nrfe','nrfe'),('rmse','rmse')]:
        v=get(original);x['mean_'+prefix]=(v[i]+v[j])/2;x['max_'+prefix]=np.maximum(v[i],v[j])
    for c in ['saturation_low','saturation_high','dynamic_range']:
        v=get(c);x['mean_'+c]=(v[i]+v[j])/2
    v=get('dynamic_range');x['difference_dynamic_range']=abs(v[i]-v[j])
    v=get('fit_failed');x['fit_failed']=np.maximum(v[i],v[j])
    for c in DOSE_FEATURES:
        v=get(c);assert np.max(v)-np.min(v)<1e-7,(key,c,np.min(v),np.max(v))
        x[c]=np.full(len(i),v[0])
    models=df.depmap_id.astype(str).to_numpy()
    tie=np.fromiter((int.from_bytes(hashlib.sha256((key+'|'+models[ii]+'|'+models[jj]).encode()).digest()[:8],'big') for ii,jj in zip(i,j)),dtype=np.uint64,count=len(i))
    return df,i,j,pd.DataFrame(x)[FEATURES],tie

def get_scores(df,i,j,x,models,mean_model):
    raw=df.raw_auc.to_numpy();fit=df.fit_auc.to_numpy()
    base,cell,drug=mean_model
    means=np.array([base+cell.get(c,0)+drug.get(d,0) for c,d in zip(df.depmap_id,df.structure_key)])
    scores={'gap_raw':x.raw_gap.to_numpy(),'gap_fit':x.fit_gap.to_numpy(),'additive_mean':abs(means[i]-means[j]),'repeat_agreement':x.repeat_agreement.to_numpy(),'standardized_gap':x.standardized_gap.to_numpy(),'nrfe_curve':-x.max_nrfe.to_numpy()}
    risks={}
    for name in LEARNED:
        if name=='isotonic_gap':risk=models[name].predict(x.raw_gap.to_numpy())
        elif name=='hgb_gap':risk=models[name].predict(x[['raw_gap']])
        elif name=='hgb_dose':risk=models[name].predict(x[DOSE_FEATURES])
        else:risk=models[name].predict(x[FEATURES])
        risks[name]=np.clip(risk,0,1);scores[name]=-risks[name]
    directions={'raw':raw[i]-raw[j],'fit':fit[i]-fit[j],'mean':means[i]-means[j]}
    return scores,risks,directions

def method_error(name,directions,target_difference):
    direction=directions['fit' if name=='gap_fit' else 'mean' if name=='additive_mean' else 'raw']
    return ranking_error(direction,target_difference)

def software_check():
    assert np.array_equal(ranking_error([1,-1,0,1],[1,1,1,0]),[0,1,.5,.5])
    s=np.array([1.,1.,3.,0.]);h=np.array([5,3,2,1],dtype=np.uint64)
    assert np.array_equal(selected(s,h,.5),[2,1])
    assert np.array_equal(selected(s,h,1),[2,1,0,3])
    assert np.allclose(ranking_error([1,2],[3,4]),ranking_error(2*np.array([1,2]),np.array([3,4])))
    return {'rank_ties':True,'deterministic_coverage':True,'positive_affine_rank_invariance':True,'synthetic_is_software_only':True}
