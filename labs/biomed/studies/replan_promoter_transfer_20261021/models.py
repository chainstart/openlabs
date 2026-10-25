"""Frozen-source features and grouped calibration. No test-dependent fitting."""
from common import *
import numpy as np
from sklearn.linear_model import LinearRegression,Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.ensemble import HistGradientBoostingRegressor
CONTEXTS={
 'klein_wt':{'dataset':'klein','source':0,'target':1},
 'tovar_ins':{'dataset':'tovar','source':0,'target':1},
 'tovar_scp1':{'dataset':'tovar','source':2,'target':3},
}
POINT=['identity','affine','ridge','class_mean','author_affine','base_hgb','precision_hgb']
RISK=['constant','source_sem','source_sem_plus_dna','base_hgb','precision_hgb']
SEED=20261021
def subset(d,idx):return {k:v[idx] for k,v in d.items()}
def load_part(dataset,split):
    with np.load(ART/'analysis_inputs'/f'{dataset}_{split}.npz',allow_pickle=False) as z:return {k:z[k] for k in z.files}
def weights(groups):
    u,c=np.unique(groups,return_counts=True);counts=dict(zip(u,c))
    return np.array([len(groups)/len(u)/counts[g] for g in groups])
def group_average(values,groups):
    u,inv=np.unique(groups,return_inverse=True)
    if np.ndim(values)==1:return u,np.bincount(inv,weights=values)/np.bincount(inv)
    return u,np.column_stack([np.bincount(inv,weights=values[:,j])/np.bincount(inv) for j in range(values.shape[1])])
def mse(y,p,groups):return float(group_average((y-p)**2,groups)[1].mean())
def fit_norm(train,context):
    c=CONTEXTS[context];n={};kind=c['dataset']
    for which in ['source','target']:
        a=c[which]
        if kind=='klein':
            med=np.median(train['raw'][:,a,:],axis=0)
            n[which]={'offset':(np.mean(med)-med).tolist()}
        else:
            dt=float(train['dna'][:,a].sum());rt=train['rna'][:,a,:].sum(axis=0)
            assert dt>0 and np.all(rt>0)
            n[which]={'offset':np.log2(dt/rt).tolist()}
    return n
def measurements(d,context,norm):
    c=CONTEXTS[context];out={}
    for which in ['source','target']:
        a=c[which];offset=np.array(norm[which]['offset'])
        if c['dataset']=='klein': rep=d['raw'][:,a,:]+offset
        else:rep=np.log2((d['rna'][:,a,:]+.5)/(d['dna'][:,a,None]+.5))+offset
        assert np.isfinite(rep).all()
        out[which+'_rep']=rep;out[which+'_mean']=rep.mean(axis=1)
    out['sem2']=out['source_rep'].var(axis=1,ddof=1)/out['source_rep'].shape[1]
    if c['dataset']=='tovar':
        out['dna_var']=1/(np.log(2)**2*(d['dna'][:,c['source']]+.5))
        out['target_dna_var']=1/(np.log(2)**2*(d['dna'][:,c['target']]+.5))
    else:out['dna_var']=np.zeros(len(out['sem2']));out['target_dna_var']=np.zeros(len(out['sem2']))
    return out
def fit_feature_state(train,context,meas):
    a=CONTEXTS[context]['source'];v=train['author'][:,a];finite=np.isfinite(v)
    return {'classes':sorted(set(train['classes'].tolist())),'author_available':bool(finite.any()),'author_fill':float(np.median(v[finite])) if finite.any() else 0.0}
def feature_matrix(d,context,m,state,precision=False):
    """All predictors here are source measurements, sequence or source annotation."""
    c=CONTEXTS[context];a=c['source']
    cols=[m['source_mean'],d['gc'],d['cpg']];names=['source_mean','GC','CpG']
    if c['dataset']=='tovar':
        cols += [np.log1p(d['dna'][:,a]),np.log1p(d['nbarcode'][:,a]),np.log1p(d['rna'][:,a,:].sum(axis=1))]
        names += ['source_log_DNA','source_log_barcodes','source_log_RNA']
    if state['author_available']:
        v=d['author'][:,a];ok=np.isfinite(v)
        cols += [np.where(ok,v,state['author_fill']),(~ok).astype(float)]
        names += ['source_author_estimate','source_author_missing']
        if c['dataset']=='tovar':
            cols.append(np.log2(np.maximum(np.where(ok,v,state['author_fill'])*np.log(2),1e-12)))
            names.append('source_log2_author_original_rate_interpretation')
    for cl in state['classes']:
        cols.append((d['classes']==cl).astype(float));names.append('source_annotation:'+cl)
    if precision:cols.append(np.log1p(m['sem2']));names.append('source_log1p_replicate_SEM2')
    x=np.column_stack(cols);assert np.isfinite(x).all()
    assert not any('target' in z for z in names)
    return x,names
def hgb():
    return HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=4,learning_rate=.05,min_samples_leaf=30,l2_regularization=10,early_stopping=False,random_state=SEED)
def author_matrix(d,context,state):
    v=d['author'][:,CONTEXTS[context]['source']];ok=np.isfinite(v)
    cols=[np.where(ok,v,state['author_fill']),(~ok).astype(float)]
    if CONTEXTS[context]['dataset']=='tovar':cols.append(np.log2(np.maximum(cols[0]*np.log(2),1e-12)))
    return np.column_stack(cols)
def fit_bundle(train,context):
    norm=fit_norm(train,context);m=measurements(train,context,norm);state=fit_feature_state(train,context,m)
    xb,nb=feature_matrix(train,context,m,state);xf,nf=feature_matrix(train,context,m,state,True)
    w=weights(train['groups']);y=m['target_mean'];avg=float(np.average(y,weights=w))
    pm={
      'train_mean':avg,
      'affine':LinearRegression().fit(m['source_mean'][:,None],y,sample_weight=w),
      'class_mean':{cl:float(np.average(y[train['classes']==cl],weights=w[train['classes']==cl])) for cl in state['classes']},
      'base_hgb':hgb().fit(xb,y,sample_weight=w),
      'precision_hgb':hgb().fit(xf,y,sample_weight=w),
    }
    pm['author_affine']=LinearRegression().fit(author_matrix(train,context,state),y,sample_weight=w) if state['author_available'] else None
    pm['ridge']=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=10))]).fit(xb,y,ridge__sample_weight=w,scale__sample_weight=w)
    fold=np.array([int(hashlib.sha256(('risk-oof:'+g).encode()).hexdigest()[:8],16)%5 for g in train['groups']])
    oof=np.full(len(y),np.nan)
    for f in range(5):
        fit=fold!=f;hold=~fit;assert fit.any() and hold.any()
        tr=subset(train,fit);ho=subset(train,hold);no=fit_norm(tr,context)
        mt=measurements(tr,context,no);mh=measurements(ho,context,no)
        lm=LinearRegression().fit(mt['source_mean'][:,None],mt['target_mean'],sample_weight=weights(tr['groups']))
        oof[hold]=(mh['target_mean']-lm.predict(mh['source_mean'][:,None]))**2
    assert np.isfinite(oof).all()
    risk_mean=float(np.average(oof,weights=w));sem=float(np.average(m['sem2'],weights=w));sem_dna=float(np.average(m['sem2']+m['dna_var'],weights=w))
    rm={'constant':risk_mean,'source_sem_scale':risk_mean/max(sem,1e-12),'source_sem_dna_scale':risk_mean/max(sem_dna,1e-12),
        'base_hgb':hgb().fit(xb,np.log1p(oof),sample_weight=w),
        'precision_hgb':hgb().fit(xf,np.log1p(oof),sample_weight=w)}
    _,gs=group_average(m['sem2'],train['groups'])
    return dict(context=context,norm=norm,state=state,point=pm,risk=rm,base_features=nb,precision_features=nf,oof_squared_error=oof,source_precision_quartile=float(np.quantile(gs,.25)),training_groups=len(np.unique(train['groups'])),seed=SEED)
def predict_bundle(bundle,d):
    context=bundle['context'];m=measurements(d,context,bundle['norm']);state=bundle['state'];p=bundle['point'];r=bundle['risk']
    xb,_=feature_matrix(d,context,m,state);xf,_=feature_matrix(d,context,m,state,True)
    pred={'identity':m['source_mean'],'ridge':p['ridge'].predict(xb),
      'affine':p['affine'].predict(m['source_mean'][:,None]),
      'class_mean':np.array([p['class_mean'].get(cl,p['train_mean']) for cl in d['classes']]),
      'base_hgb':p['base_hgb'].predict(xb),'precision_hgb':p['precision_hgb'].predict(xf)}
    pred['author_affine']=p['author_affine'].predict(author_matrix(d,context,state)) if p['author_affine'] is not None else np.full(len(xb),np.nan)
    risk={'constant':np.full(len(xb),r['constant']),'source_sem':m['sem2']*r['source_sem_scale'],
      'source_sem_plus_dna':(m['sem2']+m['dna_var'])*r['source_sem_dna_scale'],
      'base_hgb':np.maximum(0,np.expm1(r['base_hgb'].predict(xb))),
      'precision_hgb':np.maximum(0,np.expm1(r['precision_hgb'].predict(xf)))}
    slope=float(p['affine'].coef_[0]);intercept=float(p['affine'].intercept_)
    dr=m['target_rep']-(intercept+slope*m['source_rep'])
    if CONTEXTS[context]['dataset']=='klein':
        noise=(m['target_rep'].var(axis=1,ddof=1)+slope*slope*m['source_rep'].var(axis=1,ddof=1))/dr.shape[1]
    else:noise=dr.var(axis=1,ddof=1)/dr.shape[1]
    persistent=dr.mean(axis=1)**2-noise
    diag=dict(sem2=m['sem2'],dna_var=m['dna_var'],noise=noise,persistent=persistent,
       persistent_minus_poisson_DNA=persistent-m['target_dna_var']-slope*slope*m['dna_var'],source_mean=m['source_mean'],
       training_precision_quartile=np.full(len(xb),bundle['source_precision_quartile']))
    return m['target_mean'],pred,risk,diag
def risk_at_half(error,score,groups):
    u,loss=group_average(error,groups);u2,s=group_average(score,groups);assert np.array_equal(u,u2)
    k=max(1,len(u)//2);ix=np.argsort(s,kind='stable')[:k]
    return float(loss[ix].mean()),len(ix)
def validation_summary(bundle,d):
    y,p,r,diag=predict_bundle(bundle,d);g=d['groups'];loss=(y-p['affine'])**2
    return {'point_MSE':{k:mse(y,v,g) if np.isfinite(v).all() else None for k,v in p.items()},
            'risk50':{k:risk_at_half(loss,v,g)[0] for k,v in r.items()},'n':len(y),'groups':len(np.unique(g))}
