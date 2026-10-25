"""Offline reproduction from immutable saved predictions; no fitting or raw holdout access.

This verifier is deliberately independent of the expired campaign deadline/service.
It still requires the aggregate resource guard. A replay is never fresh confirmation.
"""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='2'
import argparse,pathlib,json,hashlib,datetime
import numpy as np
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--artifact-root',type=pathlib.Path,required=True)
    ap.add_argument('--prediction-manifest',type=pathlib.Path,required=True);ap.add_argument('--output-dir',type=pathlib.Path,required=True)
    args=ap.parse_args()
    assert 'openlabs-workers.slice' in pathlib.Path('/proc/self/cgroup').read_text(),'Run via resource guard'
    assert not args.output_dir.exists(),'Use a fresh output directory; existing evidence is not overwritten'
    expected=json.loads(args.prediction_manifest.read_text())['files'];results={}
    point=['identity','affine','ridge','class_mean','author_affine','base_hgb','precision_hgb']
    risk=['constant','source_sem','source_sem_plus_dna','base_hgb','precision_hgb']
    for ctx in ['klein_wt','tovar_ins','tovar_scp1']:
        p=args.artifact_root/'predictions'/(ctx+'_test.npz');assert sha(p)==expected[p.name]
        with np.load(p,allow_pickle=False) as z:d={k:z[k] for k in z.files}
        gs,ix=np.unique(d['groups'],return_inverse=True);n=len(gs);count=np.bincount(ix);k=n//2
        mean=lambda x:np.bincount(ix,weights=x)/count
        loss=np.column_stack([mean((d['y']-d['point_'+name])**2) for name in point])
        score=np.round(np.column_stack([mean(d['risk_'+name]) for name in risk]),12)
        half=lambda a,s:float(a[np.argsort(s,kind='stable')[:k]].mean())
        values=np.array([half(loss[:,1],score[:,j]) for j in range(5)])
        bp=np.empty((10000,7));br=np.empty((10000,5));rng=np.random.default_rng(20261021)
        for b in range(10000):
            draw=np.sort(rng.integers(n,size=n));bp[b]=loss[draw].mean(axis=0)
            br[b]=[half(loss[draw,1],score[draw,j]) for j in range(5)]
        ci=lambda a:np.quantile(a,[.025,.975]).tolist()
        delta=values[3]-values[4]
        results[ctx]=dict(n_groups=n,n_rows=len(d['y']),
            point={name:dict(MSE=float(loss[:,j].mean()),CI95=ci(bp[:,j])) for j,name in enumerate(point)},
            risk50={name:dict(affine_MSE=float(values[j]),CI95=ci(br[:,j])) for j,name in enumerate(risk)},
            primary=dict(absolute_improvement=float(delta),relative_improvement=float(delta/values[3]),
              CI95=ci(br[:,3]-br[:,4]),relative_CI95=ci((br[:,3]-br[:,4])/br[:,3])))
    canonical=json.loads((args.artifact_root/'analysis/test-results-corrected.json').read_text())['contexts']
    for ctx,r in results.items():
        for kind in ['point','risk50']:
            for name,v in r[kind].items():
                for key,value in v.items():assert np.allclose(value,canonical[ctx][kind][name][key],rtol=0,atol=1e-12)
        for key,value in r['primary'].items():assert np.allclose(value,canonical[ctx]['primary'][key],rtol=0,atol=1e-12)
    args.output_dir.mkdir(parents=True)
    out=dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),contexts=results,
        saved_prediction_hashes_verified=True,all_metrics_and_CIs_match_canonical=True,new_models_fitted=False,raw_holdout_reopened=False,
        fresh_confirmation=False,code_sha256=sha(__file__),prediction_manifest_sha256=sha(args.prediction_manifest))
    (args.output_dir/'replay-results.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    print('Offline replay matches all point/risk metrics and primary intervals; no new confirmation.')
if __name__=='__main__':main()
