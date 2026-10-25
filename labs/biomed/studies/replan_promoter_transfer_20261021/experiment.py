"""Frozen 12-configuration experiment; single test opening; saved-prediction summaries."""
from models import *
import pickle
def check_freeze():
    f=json.loads((DATA/'freeze.json').read_text())
    for p,h in f['code_sha256'].items():assert sha(p)==h,('changed frozen code',p)
    for ds,parts in f['partitions']['summary'].items():
        for sp,m in parts.items():assert sha(m['path'])==m['sha256']
    return f
def save_prediction(bundle,d,path):
    y,p,r,diag=predict_bundle(bundle,d)
    np.savez_compressed(path,ids=d['ids'],groups=d['groups'],y=y,
      **{'point_'+k:v for k,v in p.items()},**{'risk_'+k:v for k,v in r.items()},**{'diag_'+k:v for k,v in diag.items()})
def fit():
    f=check_freeze();assert not (ART/'test-opened.json').exists()
    out=ART/'models';out.mkdir(exist_ok=True);pr=ART/'predictions';pr.mkdir(exist_ok=True)
    assert not (DATA/'training-completed.json').exists(),'models already trained'
    result={}
    for ctx,c in CONTEXTS.items():
        tr=load_part(c['dataset'],'train');v=load_part(c['dataset'],'validation')
        bundle=fit_bundle(tr,ctx)
        with (out/(ctx+'.pkl')).open('wb') as h:pickle.dump(bundle,h)
        save_prediction(bundle,v,pr/(ctx+'_validation.npz'))
        result[ctx]=validation_summary(bundle,v)
        result[ctx]['best_validation_risk_baseline']=min([k for k in RISK if k!='precision_hgb'],key=lambda k:result[ctx]['risk50'][k])
        result[ctx]['best_validation_point_baseline']=min([k for k in POINT if k!='precision_hgb'],key=lambda k:result[ctx]['point_MSE'][k] if result[ctx]['point_MSE'][k] is not None else float('inf'))
        print(ctx,json.dumps(result[ctx]),flush=True)
    write(DATA/'training-completed.json',dict(time=now(),validation=result,configs=POINT+RISK,config_count=12,
       hyperparameter_selection='none; all registered fixed configurations retained',models={p.name:sha(p) for p in out.glob('*.pkl')}))
def open_test():
    check_freeze();t=json.loads((DATA/'training-completed.json').read_text())
    for p,h in t['models'].items():assert sha(ART/'models'/p)==h
    with (ART/'test-opened.json').open('x') as h:json.dump(dict(time=now(),reason='single frozen confirmatory execution',training_record_sha256=sha(DATA/'training-completed.json')),h)
    for ctx,c in CONTEXTS.items():
        with (ART/'models'/(ctx+'.pkl')).open('rb') as h:bundle=pickle.load(h)
        d=load_part(c['dataset'],'test');save_prediction(bundle,d,ART/'predictions'/(ctx+'_test.npz'))
    write(DATA/'test-predictions-saved.json',dict(time=now(),files={p.name:sha(p) for p in (ART/'predictions').glob('*_test.npz')}))
def ci(x):return [float(v) for v in np.quantile(x,[.025,.975])]
def summarize(ctx,split='test'):
    with np.load(ART/'predictions'/(ctx+'_'+split+'.npz'),allow_pickle=False) as z:d={k:z[k] for k in z.files}
    g=d['groups'];y=d['y'];u=np.unique(g);ng=len(u);nr=len(y)
    point=np.column_stack([group_average((y-d['point_'+k])**2,g)[1] for k in POINT])
    risks=np.column_stack([group_average(d['risk_'+k],g)[1] for k in RISK])
    al=point[:,POINT.index('affine')];k=max(1,ng//2)
    def half(a,s):return float(a[np.argsort(s,kind='stable')[:k]].mean())
    vals=np.array([half(al,risks[:,j]) for j in range(len(RISK))])
    dg=['sem2','noise','persistent','persistent_minus_poisson_DNA']
    diagnostics=np.column_stack([group_average(d['diag_'+name],g)[1] for name in dg])
    threshold=float(d['diag_training_precision_quartile'][0]);low=diagnostics[:,0]<=threshold
    rng=np.random.default_rng(SEED);nboot=10000
    bp=np.empty((nboot,len(POINT)));br=np.empty((nboot,len(RISK)));bd=np.empty((nboot,len(dg)))
    for b in range(nboot):
        ix=np.sort(rng.integers(ng,size=ng));bp[b]=point[ix].mean(axis=0);bd[b]=diagnostics[ix].mean(axis=0)
        br[b]=[half(al[ix],risks[ix,j]) for j in range(len(RISK))]
    base=RISK.index('base_hgb');full=RISK.index('precision_hgb');delta=vals[base]-vals[full]
    diff=br[:,base]-br[:,full];rel=delta/max(vals[base],1e-12)
    result=dict(context=ctx,split=split,n_rows=nr,n_groups=ng,retained_groups=k,
      point={name:dict(MSE=float(point[:,j].mean()),CI95=ci(bp[:,j]),improvement_vs_affine=float(al.mean()-point[:,j].mean()),improvement_CI95=ci(bp[:,POINT.index('affine')]-bp[:,j])) for j,name in enumerate(POINT)},
      risk50={name:dict(affine_MSE=float(vals[j]),CI95=ci(br[:,j]),precision_improvement=float(vals[j]-vals[full]),precision_improvement_CI95=ci(br[:,j]-br[:,full])) for j,name in enumerate(RISK)},
      primary=dict(absolute_improvement=float(delta),relative_improvement=float(rel),CI95=ci(diff),relative_CI95=ci(diff/np.maximum(br[:,base],1e-12)),passes=bool(delta>=.01 and rel>=.1 and ci(diff)[0]>0)),
      diagnostics={name:dict(group_mean=float(diagnostics[:,j].mean()),CI95=ci(bd[:,j])) for j,name in enumerate(dg)},
      inference='10000 paired nonparametric group bootstraps; reselect lowest-risk half within each resample; frozen-model conditional uncertainty, no training-refit uncertainty. Diagnostic negative corrected errors retained.')
    nl=int(low.sum());lowinfo=dict(training_SEM2_quartile_threshold=threshold,n_groups=nl)
    if nl>=2:
        a=np.column_stack([al[low],diagnostics[low]])
        boot=np.empty((nboot,a.shape[1]));lr=np.random.default_rng(SEED+1)
        for j in range(nboot):boot[j]=a[lr.integers(nl,size=nl)].mean(axis=0)
        lowinfo['metrics']={name:dict(mean=float(a[:,j].mean()),CI95=ci(boot[:,j])) for j,name in enumerate(['affine_MSE']+dg)}
    result['predefined_low_source_SEM_diagnostic']=lowinfo
    (ART/'analysis').mkdir(exist_ok=True)
    np.savez_compressed(ART/'analysis'/(ctx+'_'+split+'_bootstrap.npz'),point=bp,risk=br,diagnostics=bd)
    return result
if __name__=='__main__':
    guard_check();mode=sys.argv[1]
    if mode=='fit':fit()
    elif mode=='open-test':open_test()
    elif mode=='summarize':
        result={ctx:summarize(ctx) for ctx in CONTEXTS}
        write(ART/'analysis/test-results.json',dict(time=now(),contexts=result,primary_replication_passes=all(result[c]['primary']['passes'] for c in ['klein_wt','tovar_ins'])))
        print(json.dumps(result,indent=2))
