"""Independent arithmetic implementation over saved predictions, no raw test access."""
from common import *
import numpy as np,math,collections,pickle,random
guard_check()
reported=json.loads((ART/'analysis/test-results-corrected.json').read_text())['contexts']
out={}
for ctx,r in reported.items():
    with np.load(ART/'predictions'/(ctx+'_test.npz'),allow_pickle=False) as z:d={k:z[k] for k in z.files}
    with (ART/'models'/(ctx+'.pkl')).open('rb') as f:b=pickle.load(f)
    rows=collections.defaultdict(list)
    for i,g in enumerate(d['groups']):rows[str(g)].append(i)
    gs=sorted(rows);n=len(gs);k=n//2
    mean=lambda v:math.fsum(float(x) for x in v)/len(v)
    pm=list(r['point']);rm=list(r['risk50']);errs={};scores={}
    maxdiff=0.
    for p in pm:
        errs[p]={g:mean([(float(d['y'][i])-float(d['point_'+p][i]))**2 for i in ix]) for g,ix in rows.items()}
        maxdiff=max(maxdiff,abs(mean(list(errs[p].values()))-r['point'][p]['MSE']))
    for name in rm:
        scores[name]={g:round(mean([d['risk_'+name][i] for i in ix]),12) for g,ix in rows.items()}
        chosen=sorted(gs,key=lambda g:(scores[name][g],g))[:k]
        value=mean([errs['affine'][g] for g in chosen]);delta=abs(value-r['risk50'][name]['affine_MSE']);maxdiff=max(maxdiff,delta)
        if delta>1e-12:print('MISMATCH',ctx,name,value,r['risk50'][name]['affine_MSE'],delta,flush=True)
    assert maxdiff<1e-12,maxdiff
    affine=b['point']['affine'];p=affine.intercept_+affine.coef_[0]*d['diag_source_mean']
    assert np.max(np.abs(p-d['point_affine']))<1e-12
    residual=d['y']-p
    assert np.max(np.abs(residual**2-d['diag_noise']-d['diag_persistent']))<1e-11
    # Verify first 500 registered bootstrap draws against a list-based implementation.
    z=np.load(ART/'analysis'/(ctx+'_test_bootstrap_corrected.npz'))
    rng=np.random.default_rng(20261021);bootstrap_maxdiff=0.
    for rep in range(500):
        draw=[gs[j] for j in rng.integers(n,size=n)]
        for j,name in enumerate(pm):
            value=mean([errs[name][g] for g in draw]);bootstrap_maxdiff=max(bootstrap_maxdiff,abs(value-z['point'][rep,j]))
        for j,name in enumerate(rm):
            chosen=sorted(draw,key=lambda g:(scores[name][g],g))[:k]
            value=mean([errs['affine'][g] for g in chosen]);bootstrap_maxdiff=max(bootstrap_maxdiff,abs(value-z['risk'][rep,j]))
    assert bootstrap_maxdiff<1e-11,bootstrap_maxdiff
    # Independent RNG/implementation Monte Carlo audit, not replacing registered CIs.
    rng=random.Random(98173);diff=[]
    for rep in range(2000):
        draw=rng.choices(gs,k=n);v={}
        for name in ['base_hgb','precision_hgb']:
            chosen=sorted(draw,key=lambda g:(scores[name][g],g))[:k]
            v[name]=mean([errs['affine'][g] for g in chosen])
        diff.append(v['base_hgb']-v['precision_hgb'])
    out[ctx]=dict(n_rows=len(d['y']),n_groups=n,all_7_point_and_5_risk_metrics_max_abs_difference=maxdiff,
      first500_bootstrap_max_abs_difference=bootstrap_maxdiff,alternative2000_bootstrap_primary_CI95=np.quantile(diff,[.025,.975]).tolist(),
      affine_prediction_formula_verified=True,persistent_error_identity_verified=True,raw_test_reopened=False,
      prediction_sha256=sha(ART/'predictions'/(ctx+'_test.npz')))
write(DATA/'arithmetic-review.json',dict(time=now(),reviewer='Same agent, separate implementation; not independent human or agent review',contexts=out))
print(json.dumps(out,indent=2))
